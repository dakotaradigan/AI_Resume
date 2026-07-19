from __future__ import annotations

import asyncio
import contextlib
import hmac
import io
import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from ipaddress import ip_address
from pathlib import Path
from functools import lru_cache
from typing import Any, AsyncIterator, Literal
from uuid import uuid4

from anthropic import AsyncAnthropic, AnthropicError, RateLimitError
from fastapi import FastAPI, HTTPException, Request, Header, Response
from fastapi.responses import PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.routing import Route as StarletteRoute
from starlette.staticfiles import StaticFiles

try:
    from redis import asyncio as redis_asyncio
except ImportError:  # pragma: no cover - optional dependency until REDIS_URL is set
    redis_asyncio = None

from config import get_settings, Settings
from rag import initialize_rag_pipeline, RAGPipeline
from analytics.analytics import anonymize_session_id, log_query, log_feedback

logger = logging.getLogger("resume-assistant")


class _JsonLogFormatter(logging.Formatter):
    """Single-line JSON records so deployed logs are machine-greppable."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def _configure_logging() -> None:
    """Attach a JSON handler when nothing else configured the root logger.

    Under uvicorn the root logger has no handlers, so app logs would fall back
    to lastResort plain text; tests and embedders that configure logging first
    are left untouched.
    """
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonLogFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)

# Keep context small: compact early and keep fewer turns to reduce memory and token use.
MAX_SESSION_MESSAGES = 24
COMPACT_AFTER = 12
COMPACT_KEEP_RECENT = 10
COMPACT_CHAR_LIMIT = 800

# Daily conversation limit to control API costs
_daily_conversation_count: dict[str, int] = {}  # {"2026-02-03": 42}

CHAT_LIMIT_MESSAGE = (
    "You've reached the free chat limit. To continue, enter the password "
    "found on Dakota's resume."
)

BUSY_MESSAGE = (
    "Lots of interest today! The AI assistant is taking a quick break. "
    "Feel free to reach out directly at dakotaradigan@gmail.com or connect on LinkedIn. "
    "We'll be back soon!"
)

GENERIC_CHAT_ERROR = "Unable to process chat right now. Please try again soon."

JD_LIMIT_MESSAGE = (
    "You've used today's free fit analysis. Enter the password from Dakota's "
    "resume for unlimited access, or email dakotaradigan@gmail.com — he'd "
    "love to hear about the role."
)

PDF_LOCKED_MESSAGE = (
    "The PDF download is unlocked with the password found on Dakota's "
    "resume — the same one that unlocks unlimited chat."
)

# History sentinel marking a completed fit analysis; brief mode requires it.
JD_SENTINEL = "[jd-analysis]"

# Strip BOTH tag forms (opening and closing) case-insensitively so pasted
# text can't forge or break the prompt delimiter.
_JD_TAG_RE = re.compile(r"</?\s*job_description", re.IGNORECASE)


def _sanitize_jd_text(jd_text: str) -> str:
    return _JD_TAG_RE.sub("", jd_text)

# The system prompt asks the model to end replies with a machine-readable
# follow-up line: "FOLLOWUPS: q1 | q2 | q3". It is stripped from every stored,
# cached, and returned reply; the parsed questions ride on the SSE done event.
FOLLOWUPS_MARKER = "FOLLOWUPS:"


def _split_followups(reply_text: str) -> tuple[str, list[str]]:
    """Split the trailing FOLLOWUPS marker line off a model reply."""
    lines = reply_text.rstrip().split("\n")
    if lines and lines[-1].strip().startswith(FOLLOWUPS_MARKER):
        raw = lines[-1].strip()[len(FOLLOWUPS_MARKER):]
        followups = [q.strip() for q in raw.split("|") if q.strip()][:3]
        return "\n".join(lines[:-1]).rstrip(), followups
    return reply_text, []

# Scalability: In-memory storage (easy to swap to Redis later)
# Wrapped in SessionStore class for async-safe access
class SessionStore:
    """
    Thread-safe session storage for async FastAPI.

    Wraps session messages, metadata, and rate limits with asyncio.Lock()
    to prevent race conditions when multiple coroutines access the same session.

    Migration path: Replace internal dicts with Redis when scaling to multiple workers.
    """

    def __init__(self, redis_client=None, session_ttl: int = 3600):
        self._messages: dict[str, list[dict]] = {}
        self._metadata: dict[str, dict] = {}
        self._scoped_counts: dict[tuple[str, str, str], int] = {}
        self._rate_limits: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._redis = redis_client
        self._session_ttl = session_ttl
        self._redis_prefix = "resume-assistant"

    def _history_key(self, session_id: str) -> str:
        return f"{self._redis_prefix}:session:{session_id}:history"

    def _meta_key(self, session_id: str) -> str:
        return f"{self._redis_prefix}:session:{session_id}:meta"

    def _daily_key(self, day_key: str) -> str:
        return f"{self._redis_prefix}:daily:{day_key}"

    def _rate_limit_key(self, key: str, window: float) -> str:
        bucket = int(time.time() // window)
        return f"{self._redis_prefix}:rate_limit:{key}:{bucket}"

    async def get_history(self, session_id: str) -> list[dict]:
        """Get session history, creating empty list if needed."""
        if self._redis is not None:
            entries = await self._redis.lrange(self._history_key(session_id), 0, -1)
            history: list[dict] = []
            for entry in entries:
                try:
                    history.append(json.loads(entry))
                except json.JSONDecodeError:
                    logger.warning("Skipping invalid Redis history entry for session %s", session_id)
            return history

        async with self._lock:
            if session_id not in self._messages:
                self._messages[session_id] = []
            return self._messages[session_id]

    async def set_history(self, session_id: str, history: list[dict]) -> None:
        """Replace session history (used after compaction)."""
        if self._redis is not None:
            history_key = self._history_key(session_id)
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.delete(history_key)
                if history:
                    pipe.rpush(history_key, *[json.dumps(item) for item in history])
                pipe.expire(history_key, self._session_ttl)
                await pipe.execute()
            return

        async with self._lock:
            self._messages[session_id] = history

    async def append_message(self, session_id: str, role: str, text: str) -> None:
        """Append a message to session history."""
        if self._redis is not None:
            message = json.dumps({
                "role": role,
                "content": [{"type": "text", "text": text}]
            })
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.rpush(self._history_key(session_id), message)
                pipe.expire(self._history_key(session_id), self._session_ttl)
                await pipe.execute()
            return

        async with self._lock:
            if session_id not in self._messages:
                self._messages[session_id] = []
            self._messages[session_id].append({
                "role": role,
                "content": [{"type": "text", "text": text}]
            })

    async def update_metadata(self, session_id: str) -> None:
        """Track session creation and last access time for cleanup."""
        if self._redis is not None:
            now = str(time.time())
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.hsetnx(self._meta_key(session_id), "created_at", now)
                pipe.hsetnx(self._meta_key(session_id), "unlimited", "0")
                pipe.hsetnx(self._meta_key(session_id), "user_message_count", "0")
                pipe.hset(self._meta_key(session_id), mapping={"last_access": now})
                pipe.expire(self._meta_key(session_id), self._session_ttl)
                await pipe.execute()
            return

        async with self._lock:
            now = time.time()
            if session_id not in self._metadata:
                self._metadata[session_id] = {
                    "created_at": now,
                    "last_access": now,
                    "unlimited": False,
                    "user_message_count": 0
                }
            else:
                self._metadata[session_id]["last_access"] = now

    async def check_rate_limit(self, key: str, max_requests: int, window: float = 60.0) -> bool:
        """
        Check if request is within rate limit.
        Returns True if allowed, False if limit exceeded.
        """
        if self._redis is not None:
            redis_key = self._rate_limit_key(key, window)
            count = await self._redis.incr(redis_key)
            if count == 1:
                await self._redis.expire(redis_key, max(int(window) + 1, 1))
            return count <= max_requests

        async with self._lock:
            now = time.time()
            timestamps = self._rate_limits[key]

            # Remove timestamps older than the window
            timestamps[:] = [ts for ts in timestamps if now - ts < window]

            # Check if limit exceeded
            if len(timestamps) >= max_requests:
                return False

            # Add current request timestamp
            timestamps.append(now)
            return True

    async def check_and_increment_limit(self, session_id: str, limit: int) -> tuple[bool, str]:
        """
        Atomically check chat limit and increment count if allowed.
        Returns (allowed, reason) - allowed=True if under limit.
        """
        if self._redis is not None:
            script = """
            local key = KEYS[1]
            local limit = tonumber(ARGV[1])
            local now = ARGV[2]
            local ttl = tonumber(ARGV[3])
            local blocked_message = ARGV[4]

            redis.call('HSETNX', key, 'created_at', now)
            redis.call('HSETNX', key, 'unlimited', '0')
            redis.call('HSETNX', key, 'user_message_count', '0')

            if redis.call('HGET', key, 'unlimited') == '1' then
                redis.call('HINCRBY', key, 'user_message_count', 1)
                redis.call('HSET', key, 'last_access', now)
                redis.call('EXPIRE', key, ttl)
                return {1, ''}
            end

            local current_count = tonumber(redis.call('HGET', key, 'user_message_count') or '0')
            if current_count >= limit then
                redis.call('HSET', key, 'last_access', now)
                redis.call('EXPIRE', key, ttl)
                return {0, blocked_message}
            end

            redis.call('HINCRBY', key, 'user_message_count', 1)
            redis.call('HSET', key, 'last_access', now)
            redis.call('EXPIRE', key, ttl)
            return {1, ''}
            """
            allowed, reason = await self._redis.eval(
                script,
                1,
                self._meta_key(session_id),
                limit,
                str(time.time()),
                self._session_ttl,
                CHAT_LIMIT_MESSAGE,
            )
            return bool(int(allowed)), str(reason)

        async with self._lock:
            meta = self._metadata.get(session_id, {})

            if meta.get("unlimited", False):
                meta["user_message_count"] = meta.get("user_message_count", 0) + 1
                self._metadata[session_id] = meta
                return True, ""

            current_count = meta.get("user_message_count", 0)
            if current_count >= limit:
                return False, CHAT_LIMIT_MESSAGE

            meta["user_message_count"] = current_count + 1
            self._metadata[session_id] = meta
            return True, ""

    async def set_unlimited(self, session_id: str, value: bool) -> None:
        """Set unlimited access for a session."""
        if self._redis is not None:
            now = str(time.time())
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.hsetnx(self._meta_key(session_id), "created_at", now)
                pipe.hset(self._meta_key(session_id), mapping={
                    "unlimited": "1" if value else "0",
                    "last_access": now,
                })
                pipe.expire(self._meta_key(session_id), self._session_ttl)
                await pipe.execute()
            return

        async with self._lock:
            if session_id in self._metadata:
                self._metadata[session_id]["unlimited"] = value

    async def get_remaining_quota(self, session_id: str, limit: int) -> int | None:
        """Remaining free exchanges for this identity, or None when unlimited."""
        if self._redis is not None:
            values = await self._redis.hmget(
                self._meta_key(session_id), "unlimited", "user_message_count"
            )
            unlimited = (values[0] or "0") == "1"
            count = int(values[1] or 0)
        else:
            async with self._lock:
                meta = self._metadata.get(session_id, {})
                unlimited = bool(meta.get("unlimited", False))
                count = int(meta.get("user_message_count", 0))
        if unlimited:
            return None
        return max(0, limit - count)

    async def check_and_increment_scoped_limit(
        self, key: str, scope: str, limit: int, day_key: str
    ) -> bool:
        """Atomic daily counter for a named scope (e.g. JD analyses per identity),
        independent of the chat quota. Returns True while under the limit
        (incrementing), False once the limit is reached."""
        if self._redis is not None:
            script = """
            local key = KEYS[1]
            local limit = tonumber(ARGV[1])
            local current = tonumber(redis.call('GET', key) or '0')
            if current >= limit then
                return 0
            end
            redis.call('INCR', key)
            redis.call('EXPIRE', key, 172800)
            return 1
            """
            redis_key = f"{self._redis_prefix}:quota:{scope}:{key}:{day_key}"
            allowed = await self._redis.eval(script, 1, redis_key, limit)
            return bool(int(allowed))

        async with self._lock:
            counter_key = (scope, key, day_key)
            current = self._scoped_counts.get(counter_key, 0)
            if current >= limit:
                return False
            self._scoped_counts[counter_key] = current + 1
            return True

    async def release_scoped_limit(self, key: str, scope: str, day_key: str) -> None:
        """Return a unit taken by check_and_increment_scoped_limit (floor 0).

        Called when generation fails or is cancelled after the unit was
        reserved — a visitor must never lose budget for an analysis that
        was never delivered.
        """
        if self._redis is not None:
            script = """
            local current = tonumber(redis.call('GET', KEYS[1]) or '0')
            if current > 0 then
                redis.call('DECR', KEYS[1])
            end
            return 0
            """
            redis_key = f"{self._redis_prefix}:quota:{scope}:{key}:{day_key}"
            await self._redis.eval(script, 1, redis_key)
            return

        async with self._lock:
            counter_key = (scope, key, day_key)
            current = self._scoped_counts.get(counter_key, 0)
            if current > 0:
                self._scoped_counts[counter_key] = current - 1

    async def cleanup_expired(self, max_age_seconds: int) -> int:
        """
        Remove sessions older than max_age_seconds.
        Returns count of cleaned sessions.
        """
        if self._redis is not None:
            return 0

        async with self._lock:
            now = time.time()
            expired = []

            for sid, meta in self._metadata.items():
                if now - meta.get("last_access", 0) > max_age_seconds:
                    expired.append(sid)

            for sid in expired:
                self._messages.pop(sid, None)
                self._metadata.pop(sid, None)

            return len(expired)

    async def cleanup_stale_rate_limits(self, window: float = 60.0) -> None:
        """Remove rate limit entries that haven't been used recently."""
        if self._redis is not None:
            return

        async with self._lock:
            now = time.time()
            stale_cutoff = now - (window * 2)
            stale_keys = [
                key for key, timestamps in self._rate_limits.items()
                if timestamps and timestamps[-1] < stale_cutoff
            ]
            for key in stale_keys:
                self._rate_limits.pop(key, None)

    async def reserve_daily_conversation(self, day_key: str, limit: int) -> bool:
        """Atomically reserve one unit of the global daily budget BEFORE the
        model call. Returns False once the cap is reached. Callers must
        release_daily_conversation() if generation fails or is cancelled."""
        if self._redis is not None:
            script = """
            local key = KEYS[1]
            local limit = tonumber(ARGV[1])
            local current = tonumber(redis.call('GET', key) or '0')
            if current >= limit then
                return 0
            end
            redis.call('INCR', key)
            redis.call('EXPIRE', key, 259200)
            return 1
            """
            allowed = await self._redis.eval(script, 1, self._daily_key(day_key), limit)
            return bool(int(allowed))

        async with self._lock:
            current = _daily_conversation_count.get(day_key, 0)
            if current >= limit:
                return False
            _daily_conversation_count[day_key] = current + 1
            return True

    async def release_daily_conversation(self, day_key: str) -> None:
        """Return a reserved unit after a failed or cancelled generation."""
        if self._redis is not None:
            script = """
            local current = tonumber(redis.call('GET', KEYS[1]) or '0')
            if current > 0 then
                redis.call('DECR', KEYS[1])
            end
            return 0
            """
            await self._redis.eval(script, 1, self._daily_key(day_key))
            return
        async with self._lock:
            current = _daily_conversation_count.get(day_key, 0)
            if current > 0:
                _daily_conversation_count[day_key] = current - 1

    async def close(self) -> None:
        if self._redis is None:
            return
        close = getattr(self._redis, "aclose", None)
        if close is not None:
            await close()
            return
        await self._redis.close()


# Global session store instance
_session_store: SessionStore | None = None

# Pre-cached responses for starter suggestion chips (populated lazily on first hit).
# Key = lowercased/stripped question text, Value = cached reply string.
_starter_cache: dict[str, str] = {}
# Entries must end with "?" to match the cache-key normalization in /api/chat.
STARTER_QUESTIONS = frozenset({
    "what's dakota's background?",
    "tell me about dakota's ai projects?",
    "what can dakota do for my company?",
    "how was this site built?",
})


def get_session_store() -> SessionStore:
    """Get or create the global session store."""
    global _session_store
    if _session_store is None:
        settings = get_settings()
        redis_client = None
        redis_url = settings.redis_url.strip()
        if redis_url:
            if redis_asyncio is None:
                raise RuntimeError("REDIS_URL is set but the redis package is not installed.")
            redis_client = redis_asyncio.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                health_check_interval=30,
            )
            logger.info("Using Redis-backed session store")
        _session_store = SessionStore(
            redis_client=redis_client,
            session_ttl=settings.session_max_age_seconds,
        )
    return _session_store


# Reindex lock: Prevent concurrent re-indexing operations (wastes API costs)
# Using asyncio.Lock for proper async context support
_reindex_lock: asyncio.Lock | None = None


def get_reindex_lock() -> asyncio.Lock:
    """Get or create the global reindex lock."""
    global _reindex_lock
    if _reindex_lock is None:
        _reindex_lock = asyncio.Lock()
    return _reindex_lock


def _get_client_ip(request: Request) -> str:
    """Best-effort client IP extraction for rate limits."""
    settings = get_settings()
    xff = request.headers.get("x-forwarded-for", "")
    if settings.trust_proxy_headers and xff:
        # Take the right-most IP: it was appended by the trusted proxy in front
        # of us. Left-most entries are client-supplied and trivially spoofable,
        # which would let an attacker rotate fake IPs past the rate limits.
        for forwarded_ip in reversed(xff.split(",")):
            forwarded_ip = forwarded_ip.strip()
            if not forwarded_ip:
                continue
            try:
                ip_address(forwarded_ip)
            except ValueError:
                break
            return forwarded_ip
    return request.client.host if request.client else "unknown"


def _is_loopback_host(host: str) -> bool:
    """Return True for local development hosts only."""
    if host in {"localhost", "testserver"}:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = Field(default=None, max_length=100)


class UnlockRequest(BaseModel):
    password: str
    # Accepted for backward compatibility but ignored: unlock is keyed to the
    # server-minted visitor cookie, not the client-supplied session id.
    session_id: str | None = Field(default=None, max_length=100)


class JDMatchRequest(BaseModel):
    jd_text: str = Field(..., min_length=1)
    mode: Literal["analysis", "brief"] = "analysis"
    session_id: str | None = Field(default=None, max_length=100)


class UnlockResponse(BaseModel):
    success: bool
    message: str


class FeedbackRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=100)
    rating: Literal["up", "down"]
    comment: str = Field(default="", max_length=500)
    trigger: Literal["first_response", "password_unlock", ""] = ""


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    sources: list[str] = Field(default_factory=list)
    used_rag: bool = False


# === Scalability Helper Functions ===
# Note: Rate limiting and session cleanup are now handled by SessionStore class above.


# === Data Loading Functions ===


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"File not found: {path}") from exc
    except OSError as exc:
        raise RuntimeError(f"Unable to read file: {path}") from exc


def _format_resume_context(data: dict) -> str:
    lines: list[str] = []
    personal = data.get("personal", {})
    if personal:
        name = personal.get("name", "").strip()
        title = personal.get("title", "").strip()
        summary = personal.get("summary", "").strip()
        header = " - ".join([part for part in [name, title] if part])
        if header:
            lines.append(header)
        if summary:
            lines.append(summary)

    experiences = data.get("experience", [])
    if experiences:
        lines.append("Experience:")
        for exp in experiences:
            role = exp.get("role", "")
            company = exp.get("company", "")
            duration = exp.get("duration", "")
            achievements = exp.get("achievements", []) or []
            sample_achievements = "; ".join(achievements[:3])
            lines.append(
                f"- {role} at {company} ({duration}) — {sample_achievements}".strip()
            )

    projects = data.get("projects", [])
    if projects:
        lines.append("Projects:")
        for proj in projects:
            name = proj.get("name", "")
            tagline = proj.get("tagline", "")
            highlights = "; ".join((proj.get("highlights") or [])[:2])
            lines.append(
                f"- {name}: {tagline}".strip()
                + (f" — {highlights}" if highlights else "")
            )

    skills = data.get("skills", {})
    if skills:
        lines.append("Skills:")
        for category, items in skills.items():
            if items:
                category_name = category.replace("_", " ").title()
                lines.append(f"- {category_name}: {', '.join(items)}")

    education = data.get("education", [])
    if education:
        lines.append("Education:")
        for edu in education:
            degree = edu.get("degree", "")
            school = edu.get("school", "")
            graduation = edu.get("graduation", "")
            edu_parts = [p for p in [degree, school, graduation] if p]
            if edu_parts:
                lines.append(f"- {', '.join(edu_parts)}")

    certifications = data.get("certifications", [])
    if certifications:
        lines.append("Certifications:")
        # Include top 5 most recent/relevant certifications
        for cert in certifications[:5]:
            name = cert.get("name", "")
            issuer = cert.get("issuer", "")
            date = cert.get("date", "")
            cert_parts = [p for p in [name, issuer, date] if p]
            if cert_parts:
                lines.append(f"- {' - '.join(cert_parts)}")

    return "\n".join(lines)


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    settings = get_settings()
    return _read_text(settings.data_dir / "system_prompt.txt").strip()


@lru_cache(maxsize=1)
def load_jd_match_prompt() -> str:
    settings = get_settings()
    return _read_text(settings.data_dir / "jd_match_prompt.txt").strip()


@lru_cache(maxsize=1)
def load_resume_context() -> str:
    """
    Legacy static context loader (kept for fallback if RAG disabled).
    When RAG is enabled, use retrieve_rag_context() instead.
    """
    settings = get_settings()
    resume_path = settings.data_dir / "resume.json"
    try:
        data = json.loads(resume_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Resume data not found: {resume_path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Resume data is not valid JSON: {resume_path}") from exc
    except OSError as exc:
        raise RuntimeError(f"Unable to read resume data: {resume_path}") from exc
    return _format_resume_context(data)


@lru_cache(maxsize=1)
def load_resume_json_public() -> dict:
    """
    Public resume payload for the frontend UI.
    Intentionally excludes phone number.
    """
    settings = get_settings()
    resume_path = settings.data_dir / "resume.json"
    try:
        data = json.loads(resume_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Resume data not found: {resume_path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Resume data is not valid JSON: {resume_path}") from exc
    except OSError as exc:
        raise RuntimeError(f"Unable to read resume data: {resume_path}") from exc

    personal = dict(data.get("personal", {}) or {})
    personal.pop("phone", None)
    data["personal"] = personal
    return data


SITE_URL = "https://www.dakotaradigan.io"


@lru_cache(maxsize=1)
def render_llms_text() -> str:
    """Markdown digest of the resume for LLM crawlers (llms.txt convention).

    Rendered from the same phone-scrubbed payload as /api/resume so it can
    never drift from the source of truth.
    """
    data = load_resume_json_public()
    personal = data.get("personal", {})
    lines: list[str] = [
        f"# {personal.get('name', 'Dakota Radigan')} — {personal.get('title', '')}".rstrip(" —"),
        "",
        f"> {personal.get('summary', '').strip()}",
        "",
        f"- Site (chat with an AI assistant about this resume): {SITE_URL}",
        f"- Resume as JSON: {SITE_URL}/api/resume",
        f"- MCP endpoint (streamable HTTP, one tool: get_resume): {SITE_URL}/mcp",
        f"- Email: {personal.get('email', '')}",
        f"- LinkedIn: {personal.get('linkedin', '')}",
        f"- Location: {personal.get('location', '')}",
        "",
        "## Experience",
    ]
    for job in data.get("experience", []):
        lines.append(
            f"### {job.get('role', '')} — {job.get('company', '')} ({job.get('duration', '')})"
        )
        if job.get("description"):
            lines.append(job["description"].strip())
        for achievement in (job.get("achievements") or [])[:3]:
            lines.append(f"- {achievement}")
        lines.append("")
    lines.append("## Projects")
    for project in data.get("projects", []):
        lines.append(f"### {project.get('name', '')} — {project.get('tagline', '')}")
        if project.get("impact"):
            lines.append(f"- Impact: {project['impact']}")
        if project.get("tech_stack"):
            lines.append(f"- Stack: {', '.join(project['tech_stack'])}")
        lines.append("")
    lines.append("## Skills")
    for category, items in (data.get("skills") or {}).items():
        label = category.replace("_", " ").title()
        lines.append(f"- {label}: {', '.join(items)}")
    lines.append("")
    lines.append("## Certifications")
    for cert in data.get("certifications", []):
        entry = f"- {cert.get('name', '')} — {cert.get('issuer', '')}"
        if cert.get("date"):
            entry += f" ({cert['date']})"
        lines.append(entry)
    lines.append("")
    return "\n".join(lines)


# PDF palette: print-friendly values of the site's light-theme tokens.
_PDF_TEXT = "#232830"
_PDF_MUTED = "#6b7280"
_PDF_ACCENT = "#b3641a"


@lru_cache(maxsize=1)
def render_resume_pdf() -> bytes:
    """Polished PDF rendered from the phone-scrubbed resume payload.

    Import is local so the app still boots if reportlab is absent in a
    stripped-down dev env; the route turns that into a 500 with a clear log.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    data = load_resume_json_public()
    personal = data.get("personal", {})

    def esc(value: Any) -> str:
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    name_style = ParagraphStyle(
        "name", fontName="Helvetica-Bold", fontSize=21, leading=25,
        textColor=colors.HexColor(_PDF_TEXT), alignment=TA_LEFT,
    )
    contact_style = ParagraphStyle(
        "contact", fontName="Helvetica", fontSize=9, leading=12,
        textColor=colors.HexColor(_PDF_MUTED),
    )
    section_style = ParagraphStyle(
        "section", fontName="Helvetica-Bold", fontSize=10.5, leading=13,
        textColor=colors.HexColor(_PDF_ACCENT), spaceBefore=10, spaceAfter=2,
    )
    role_style = ParagraphStyle(
        "role", fontName="Helvetica-Bold", fontSize=10, leading=13,
        textColor=colors.HexColor(_PDF_TEXT), spaceBefore=5,
    )
    body_style = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=9, leading=12,
        textColor=colors.HexColor(_PDF_TEXT),
    )
    bullet_style = ParagraphStyle(
        "bullet", parent=body_style, leftIndent=10, bulletIndent=2, spaceAfter=1,
    )

    story: list[Any] = [
        Paragraph(esc(personal.get("name", "")), name_style),
        Paragraph(esc(personal.get("title", "")), body_style),
        Spacer(1, 4),
        Paragraph(
            " · ".join(
                esc(part) for part in (
                    personal.get("location"), personal.get("email"),
                    personal.get("linkedin"), SITE_URL,
                ) if part
            ),
            contact_style,
        ),
        Spacer(1, 6),
    ]

    def section(title: str) -> None:
        story.append(Paragraph(title.upper(), section_style))
        story.append(
            HRFlowable(width="100%", thickness=0.7, color=colors.HexColor(_PDF_ACCENT))
        )
        story.append(Spacer(1, 3))

    if personal.get("summary"):
        section("Summary")
        story.append(Paragraph(esc(personal["summary"]), body_style))

    section("Experience")
    for job in data.get("experience", []):
        story.append(
            Paragraph(
                f"{esc(job.get('role', ''))} — {esc(job.get('company', ''))}"
                f" <font color='{_PDF_MUTED}' size='8.5'>({esc(job.get('duration', ''))})</font>",
                role_style,
            )
        )
        for achievement in (job.get("achievements") or [])[:4]:
            story.append(Paragraph(esc(achievement), bullet_style, bulletText="•"))

    section("Projects")
    for project in data.get("projects", []):
        story.append(
            Paragraph(
                f"{esc(project.get('name', ''))} — {esc(project.get('tagline', ''))}",
                role_style,
            )
        )
        detail = project.get("impact") or project.get("description") or ""
        if detail:
            story.append(Paragraph(esc(detail), bullet_style, bulletText="•"))

    section("Skills")
    for category, items in (data.get("skills") or {}).items():
        label = category.replace("_", " ").title()
        story.append(
            Paragraph(f"<b>{esc(label)}:</b> {esc(', '.join(items))}", body_style)
        )

    if data.get("education"):
        section("Education")
        for entry in data["education"]:
            story.append(
                Paragraph(
                    f"{esc(entry.get('degree', ''))} — {esc(entry.get('school', ''))}"
                    f" <font color='{_PDF_MUTED}' size='8.5'>({esc(entry.get('graduation', ''))})</font>",
                    body_style,
                )
            )

    section("Certifications")
    for cert in data.get("certifications", []):
        line = f"{esc(cert.get('name', ''))} — {esc(cert.get('issuer', ''))}"
        if cert.get("date"):
            line += f" ({esc(cert['date'])})"
        story.append(Paragraph(line, bullet_style, bulletText="•"))

    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=f"{personal.get('name', 'Resume')} — Resume",
        author=personal.get("name", ""),
    ).build(story)
    return buffer.getvalue()


def retrieve_rag_context(
    rag_pipeline: RAGPipeline | None,
    query: str,
    limit: int = 4,
    score_threshold: float = 0.30,
) -> tuple[str, bool, list[dict[str, Any]]]:
    """
    Retrieve relevant resume context using RAG pipeline.

    Args:
        rag_pipeline: Initialized RAG pipeline (None if disabled)
        query: User's message to search for relevant context
        limit: Maximum number of chunks to retrieve
        score_threshold: Minimum similarity score (0-1)

    Returns:
        (context, used_rag, sources) — sources is [{"title": str, "score": float}]
        for the retrieved chunks. The non-streaming API maps these to bare
        titles to keep the ChatResponse.sources contract (list[str]) unchanged.
    """
    if rag_pipeline is None:
        logger.warning("RAG pipeline not initialized, falling back to static context")
        return load_resume_context(), False, []

    try:
        results = rag_pipeline.search(query, limit=limit, score_threshold=score_threshold)

        if not results:
            logger.info(f"No RAG results found for query (threshold={score_threshold}), using static context")
            return load_resume_context(), False, []

        # Format retrieved chunks into context string
        context_parts = []
        sources = []
        for idx, result in enumerate(results, 1):
            context_parts.append(
                f"[Context {idx}: {result['title']}]\n{result['text']}"
            )
            sources.append({
                "title": result["title"],
                "score": round(float(result.get("score") or 0.0), 3),
            })

        return "\n\n".join(context_parts), True, sources

    except Exception as exc:
        logger.exception("RAG retrieval failed, falling back to static context")
        return load_resume_context(), False, []


async def _compact_session_history(session_id: str, store: SessionStore) -> None:
    """Compact session history to prevent unbounded growth."""
    history = await store.get_history(session_id)
    if len(history) <= COMPACT_AFTER:
        return

    early = history[:-COMPACT_KEEP_RECENT]
    recent = history[-COMPACT_KEEP_RECENT:]

    def _extract_text(msg: dict) -> str:
        parts = []
        for block in msg.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return " ".join(parts).strip()

    summary_lines: list[str] = []
    for msg in early:
        role = msg.get("role", "unknown")
        text = _extract_text(msg)
        if text:
            summary_lines.append(f"{role.capitalize()}: {text}")

    summary_text = "\n".join(summary_lines)[:COMPACT_CHAR_LIMIT]
    # Anthropic's Messages API only accepts "user"/"assistant" roles in `messages`,
    # so the compacted summary must be a user turn.
    summary_message = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": (
                    "Earlier conversation summary (compacted for context):\n"
                    f"{summary_text}"
                ),
            }
        ],
    }

    new_history = [summary_message, *recent]
    if len(new_history) > MAX_SESSION_MESSAGES:
        new_history = new_history[-MAX_SESSION_MESSAGES:]

    await store.set_history(session_id, new_history)


# === Chat turn helpers (shared by /api/chat and /api/chat/stream) ===


@dataclass(frozen=True)
class ChatTurnContext:
    """Validated identity + input for one chat turn."""

    session_id: str
    visitor_id: str
    message: str


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _resolve_visitor_id(request: Request) -> tuple[str, bool]:
    """Server-owned visitor identity from the HttpOnly cookie.

    Quotas and unlock are keyed to this (not the client-supplied session_id,
    which is history-only) so clearing localStorage no longer resets limits
    and session ids stop acting as bearer tokens for entitlements (SEC-01).
    Only UUID-format cookie values are accepted. Returns (visitor_id, is_new).
    """
    settings = get_settings()
    raw = request.cookies.get(settings.visitor_cookie_name, "")
    if raw and _UUID_RE.match(raw):
        return raw, False
    return str(uuid4()), True


def _set_visitor_cookie(response: Response, visitor_id: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.visitor_cookie_name,
        value=visitor_id,
        max_age=settings.visitor_ttl_seconds,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.environment == "production",
    )


async def _run_chat_guardrails(
    payload: ChatRequest,
    request: Request,
    store: SessionStore,
    settings: Settings,
    *,
    max_chars: int | None = None,
    consume_quota: bool = True,
) -> ChatTurnContext:
    """Run every pre-generation guardrail. Raises HTTPException before any
    stream starts, so error handling is identical for both chat endpoints."""
    session_id = payload.session_id or str(uuid4())
    visitor_id, _ = _resolve_visitor_id(request)

    # Session cleanup: remove old sessions periodically
    expired_count = await store.cleanup_expired(settings.session_max_age_seconds)
    if expired_count > 0:
        logger.info(f"Cleaned up {expired_count} expired sessions")
    await store.cleanup_stale_rate_limits()

    # Track last access for cleanup — for the chat session AND the visitor
    # identity (whose metadata carries quota/unlock state; without a fresh
    # last_access, cleanup_expired would wipe it and reset the quota).
    await store.update_metadata(session_id)
    await store.update_metadata(visitor_id)

    # Rate limiting: prevent abuse (default key = client IP)
    rate_limit_key = _get_client_ip(request)
    allowed = await store.check_rate_limit(
        rate_limit_key,
        max_requests=settings.rate_limit_requests_per_minute
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=(
                "Rate limit exceeded. Please wait a moment before sending "
                "another message. This helps ensure fair access for all visitors."
            ),
        )

    # Daily conversation budget: atomically reserve BEFORE the model call.
    # Endpoints release the unit when generation fails or is cancelled.
    # The limit is env-tunable (DAILY_CONVERSATION_LIMIT on Railway).
    today = date.today().isoformat()
    if not await store.reserve_daily_conversation(today, settings.daily_conversation_limit):
        raise HTTPException(status_code=503, detail=BUSY_MESSAGE)

    # Input bounds (before consuming chat quota). Any rejection below returns
    # the reserved daily unit — client errors must not consume budget.
    async def _reject(exc: HTTPException) -> None:
        await store.release_daily_conversation(today)
        raise exc

    message = (payload.message or "").strip()
    if not message:
        await _reject(HTTPException(status_code=400, detail="Message cannot be empty."))
    limit_chars = max_chars or settings.max_user_message_chars
    if len(message) > limit_chars:
        await _reject(HTTPException(
            status_code=413,
            detail=f"Message too long (max {limit_chars} characters).",
        ))

    if not settings.anthropic_api_key:
        await _reject(HTTPException(
            status_code=503,
            detail="Anthropic API key not configured. Set ANTHROPIC_API_KEY.",
        ))

    # Chat limit protection: free users limited to N exchanges (atomic
    # check+increment), keyed to the visitor id. JD analyses skip this — they
    # draw from their own daily budget so the recruiter happy path never
    # dead-ends on chat quota.
    if consume_quota:
        allowed, reason = await store.check_and_increment_limit(
            visitor_id, settings.free_chat_limit
        )
        if not allowed:
            await _reject(HTTPException(status_code=403, detail=reason))

    return ChatTurnContext(session_id=session_id, visitor_id=visitor_id, message=message)


def _build_chat_context(
    message: str,
    rag_pipeline: RAGPipeline | None,
    settings: Settings,
) -> tuple[str, bool, list[dict[str, Any]]]:
    """Build the full system message (prompt + resume context) for one turn.

    Blocking (RAG embed + search); call via asyncio.to_thread.
    """
    system_prompt = load_system_prompt()
    if settings.use_rag and rag_pipeline is not None:
        resume_context, used_rag, sources = retrieve_rag_context(
            rag_pipeline, message, 4, 0.30
        )
        context_label = "RETRIEVED CONTEXT" if used_rag else "RESUME DATA"
    else:
        resume_context = load_resume_context()
        context_label = "RESUME DATA"
        used_rag = False
        sources = []
    return f"{system_prompt}\n\n[{context_label}]\n{resume_context}", used_rag, sources


def _make_anthropic_client(settings: Settings) -> AsyncAnthropic:
    return AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.api_timeout_seconds,
        max_retries=3,  # Built-in retry with exponential backoff
    )


def _model_short_label(model_id: str) -> str:
    """Human label for status events: 'claude-sonnet-5' -> 'Sonnet'."""
    lowered = model_id.lower()
    for family in ("opus", "sonnet", "haiku"):
        if family in lowered:
            return family.capitalize()
    return model_id


_ROUTER_SYSTEM = (
    "Classify the user question about a resume as 'simple' (single factual "
    "lookup) or 'complex' (synthesis, comparison, multi-part, or open-ended). "
    "Reply with exactly one word: simple or complex."
)


# Newer Anthropic models (Sonnet 5, Opus 4.7/4.8, Fable/Mythos) reject requests
# that set non-default sampling params like temperature with 400 Bad Request.
_NO_SAMPLING_MODEL_MARKERS = ("sonnet-5", "opus-4-7", "opus-4-8", "fable", "mythos")


def _sampling_kwargs(model_id: str, temperature: float) -> dict[str, Any]:
    """Sampling params for a messages call, omitted for models that reject them."""
    lowered = model_id.lower()
    if any(marker in lowered for marker in _NO_SAMPLING_MODEL_MARKERS):
        return {}
    return {"temperature": temperature}


def _is_fast_path_simple(message: str) -> bool:
    """Trivial queries skip the classifier and go straight to the simple model."""
    if len(message) >= 120:
        return False
    lowered = message.lower()
    return " and " not in lowered and "," not in message and message.count("?") <= 1


async def _route_model(
    message: str, client: AsyncAnthropic, settings: Settings
) -> tuple[str, str]:
    """Pick the generation model for this turn. Returns (model_id, reason).

    Fails safe: any classifier error routes to the primary (most capable)
    model, bounded by the existing rate and daily limits.
    """
    if _is_fast_path_simple(message):
        return settings.anthropic_model_simple, "fast-path"
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=settings.anthropic_router_model,
                max_tokens=4,
                **_sampling_kwargs(settings.anthropic_router_model, 0.0),
                system=_ROUTER_SYSTEM,
                messages=[{"role": "user", "content": [{"type": "text", "text": message}]}],
            ),
            timeout=2.0,
        )
        label = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip().lower()
    except Exception:
        logger.warning("Model router classification failed; using primary model")
        return settings.anthropic_model, "router-error"
    if label == "simple":
        return settings.anthropic_model_simple, "simple"
    return settings.anthropic_model, "complex"


async def _prepare_generation(
    message: str,
    rag_pipeline: RAGPipeline | None,
    client: AsyncAnthropic,
    settings: Settings,
) -> tuple[str, bool, list[dict[str, Any]], str, str]:
    """Run context retrieval and model routing concurrently (routing must not
    add serial time-to-first-token)."""
    (system_message, used_rag, sources), (model_id, route_reason) = await asyncio.gather(
        asyncio.to_thread(_build_chat_context, message, rag_pipeline, settings),
        _route_model(message, client, settings),
    )
    return system_message, used_rag, sources, model_id, route_reason


def _build_api_messages(history: list[dict], message: str) -> list[dict]:
    # Drop any history entries with roles the Messages API rejects
    # (e.g. "system" summaries written by older compaction code).
    return [
        *(msg for msg in history if msg.get("role") in ("user", "assistant")),
        {"role": "user", "content": [{"type": "text", "text": message}]},
    ]


async def _persist_chat(
    store: SessionStore,
    settings: Settings,
    session_id: str,
    message: str,
    reply_text: str,
    *,
    history_was_empty: bool,
    cache_key: str,
    model_id: str = "",
    route_reason: str = "",
) -> None:
    """Post-generation bookkeeping. reply_text must already be FOLLOWUPS-stripped.
    (The daily budget was reserved up front in the guardrails.)"""
    # Cache response for starter questions (populate lazily on first real answer)
    if history_was_empty and cache_key in STARTER_QUESTIONS:
        _starter_cache[cache_key] = reply_text

    await store.append_message(session_id, "user", message)
    await store.append_message(session_id, "assistant", reply_text)
    await _compact_session_history(session_id, store)

    # Log query for analytics (gitignored files; hashed id, never the live
    # bearer session id)
    await asyncio.to_thread(
        log_query,
        anonymize_session_id(session_id, settings.session_hash_secret),
        message,
        reply_text,
        model_id,
        route_reason,
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    """Format one SSE frame. json.dumps guarantees single-line data."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _initialize_rag(settings) -> RAGPipeline | None:
    """
    Initialize RAG pipeline on application startup.

    Args:
        settings: Application settings

    Returns:
        Initialized RAG pipeline, or None if disabled/failed
    """
    if not settings.use_rag:
        logger.info("RAG disabled in settings, using static resume context")
        return None

    if not settings.openai_api_key:
        logger.warning("OpenAI API key not configured, RAG disabled (falling back to static context)")
        return None

    if not (settings.qdrant_url or "").strip():
        logger.warning("QDRANT_URL not configured, RAG disabled (falling back to static context)")
        return None

    try:
        resume_path = settings.data_dir / "resume.json"
        logger.info("Initializing RAG pipeline...")
        pipeline = initialize_rag_pipeline(
            openai_api_key=settings.openai_api_key,
            resume_path=resume_path,
            qdrant_url=settings.qdrant_url,
            qdrant_api_key=settings.qdrant_api_key,
            projects_dir=settings.data_dir / "projects",
        )
        logger.info("✅ RAG pipeline initialized successfully")
        return pipeline

    except Exception as exc:
        logger.exception("Failed to initialize RAG pipeline, falling back to static context")
        return None


# Anthropic model ids are lowercase words joined by hyphens (claude-opus-4-8).
# Anything else — capitals, dots, spaces — 404s on every request, which
# presents as "chat is down" while deploys look green.
_MODEL_ID_RE = re.compile(r"^claude-[a-z0-9-]+$")


def _warn_on_suspicious_model_ids(settings: Settings) -> None:
    for env_name, value in (
        ("ANTHROPIC_MODEL", settings.anthropic_model),
        ("ANTHROPIC_MODEL_SIMPLE", settings.anthropic_model_simple),
        ("ANTHROPIC_ROUTER_MODEL", settings.anthropic_router_model),
    ):
        looks_like_claude_id = value.lower().startswith("claude")
        if looks_like_claude_id and not _MODEL_ID_RE.match(value):
            logger.error(
                "%s looks invalid: %r — model ids are lowercase with hyphens "
                "(e.g. claude-opus-4-8); the API will reject every request.",
                env_name,
                value,
            )


def _build_mcp_server():
    """MCP server with exactly ONE tool: get_resume (data-only).

    An LLM-invoking tool (ask_resume) was reviewed and rejected: it would be
    an unauthenticated LLM proxy able to starve the global daily budget. The
    connected client's own model does the reasoning over the raw resume.
    """
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    server = FastMCP(
        "dakota-resume",
        instructions=(
            "Dakota Radigan's resume. Call get_resume for the full structured "
            "resume JSON (experience, projects, skills, education, certifications)."
        ),
        stateless_http=True,
    )
    # The sub-app is mounted at /mcp by the parent app; serve at its root.
    server.settings.streamable_http_path = "/"
    # The SDK's DNS-rebinding protection rejects any Host not on its
    # allowlist (default: localhost only) with 421 — including the real
    # domain. This server is public, unauthenticated, and data-only, so
    # rebinding protection defends nothing; disable it rather than chase
    # the domain list.
    server.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )

    @server.tool()
    def get_resume() -> dict:
        """Dakota Radigan's full resume as structured JSON (phone number excluded)."""
        return load_resume_json_public()

    return server


def build_app() -> FastAPI:
    _configure_logging()
    mcp_server = _build_mcp_server()
    mcp_asgi_app = mcp_server.streamable_http_app()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        # The MCP session manager requires a running lifespan; the session
        # store close was previously an on_event("shutdown") handler.
        async with mcp_server.session_manager.run():
            yield
        await get_session_store().close()

    app = FastAPI(
        title="Resume Assistant",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    settings = get_settings()
    _warn_on_suspicious_model_ids(settings)

    app.state.reindex_status = {
        "running": False,
        "started_at": None,
        "finished_at": None,
        "last_result": None,
        "last_error": None,
    }

    # Initialize RAG pipeline on startup and store in app.state
    app.state.rag_pipeline = _initialize_rag(settings)

    # CORS: Environment-aware configuration
    # Development: Allow all origins for local testing
    # Production: Restrict to specific domain (update when deploying)
    if settings.environment == "production":
        allowed_origins = [
            "https://chat.dakotaradigan.io",
            "https://www.dakotaradigan.io",
            "https://dakotaradigan.io",
            "https://dakotaradigan.ai",
            "https://www.dakotaradigan.ai",
        ]
        allow_credentials = True
    else:
        # Development: support local servers + direct file open flows.
        # Note: credentials + wildcard origin is invalid per the CORS spec.
        allowed_origins = ["*"]
        allow_credentials = False

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Security headers: protect against clickjacking, MIME sniffing, and XSS
    from starlette.middleware.base import BaseHTTPMiddleware

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            # Force revalidation (cheap 304s via StaticFiles ETags) so shipped
            # frontend changes take effect immediately — HTML depends on fresh
            # app.js to enable controls, and stale caches froze the JD button.
            if "cache-control" not in response.headers:
                response.headers["Cache-Control"] = "no-cache"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data:; "
                "connect-src 'self'"
            )
            return response

    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    def get_rag_pipeline() -> RAGPipeline | None:
        """FastAPI dependency that returns the initialized RAG pipeline."""
        return getattr(app.state, "rag_pipeline", None)

    def _require_admin(x_admin_token: str | None, request: Request) -> None:
        if settings.admin_token:
            if not hmac.compare_digest(x_admin_token or "", settings.admin_token):
                raise HTTPException(status_code=401, detail="Unauthorized.")
            return
        client_host = request.client.host if request.client else ""
        if settings.environment != "development" or not _is_loopback_host(client_host):
            raise HTTPException(
                status_code=503,
                detail="Admin endpoint disabled (ADMIN_TOKEN not configured).",
            )

    @app.get("/health/rag")
    async def rag_health() -> dict[str, Any]:
        """Check RAG pipeline status for monitoring."""
        rag_pipeline = get_rag_pipeline()
        collection_exists: bool | None = None
        points_count: int | None = None

        if rag_pipeline is not None:
            try:
                collection_exists = await asyncio.to_thread(
                    rag_pipeline.qdrant_client.collection_exists,
                    collection_name=rag_pipeline.collection_name,
                )
                if collection_exists:
                    count_result = await asyncio.to_thread(
                        rag_pipeline.qdrant_client.count,
                        collection_name=rag_pipeline.collection_name,
                        exact=True,
                    )
                    points_count = int(getattr(count_result, "count", 0) or 0)
                else:
                    points_count = 0
            except Exception:
                logger.exception("Failed to check RAG collection health")

        vector_db_live = bool(collection_exists and (points_count or 0) > 0)
        return {
            "rag_enabled": settings.use_rag,
            "rag_initialized": rag_pipeline is not None,
            "qdrant_configured": bool(settings.qdrant_url),
            "mode": "rag" if settings.use_rag and rag_pipeline is not None else "static_fallback",
            "collection_exists": collection_exists,
            "points_count": points_count,
            "vector_db_live": vector_db_live,
        }

    @app.get("/health/models")
    async def models_health() -> dict[str, Any]:
        """Live-check each configured model against the Anthropic API.

        'Deploy succeeded' says nothing about whether the account can call
        the configured models; this endpoint does, without spending tokens.
        """
        client = _make_anthropic_client(settings)
        results: dict[str, Any] = {}
        for env_name, model_id in (
            ("ANTHROPIC_MODEL", settings.anthropic_model),
            ("ANTHROPIC_MODEL_SIMPLE", settings.anthropic_model_simple),
            ("ANTHROPIC_ROUTER_MODEL", settings.anthropic_router_model),
        ):
            try:
                await client.models.retrieve(model_id)
                results[env_name] = {"model": model_id, "status": "ok"}
            except AnthropicError as exc:
                results[env_name] = {
                    "model": model_id,
                    "status": "error",
                    "detail": str(exc)[:300],
                }
            except Exception as exc:  # pragma: no cover - unexpected transport errors
                results[env_name] = {
                    "model": model_id,
                    "status": "error",
                    "detail": f"{type(exc).__name__}: {exc}"[:300],
                }
        return results

    @app.post("/admin/cache/clear")
    async def clear_cache(
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, str]:
        """
        Clear all cached data (system prompt, resume context).

        Use this endpoint after updating resume.json or system_prompt.txt
        to refresh the cache without restarting the server.

        Note: In production, this endpoint should be protected with authentication.
        """
        _require_admin(x_admin_token, request)

        load_system_prompt.cache_clear()
        load_jd_match_prompt.cache_clear()
        load_resume_context.cache_clear()
        load_resume_json_public.cache_clear()
        render_llms_text.cache_clear()
        render_resume_pdf.cache_clear()
        _starter_cache.clear()
        logger.info("Cache cleared: prompts, resume_context, and starter responses")
        return {
            "status": "success",
            "message": "Cache cleared. Fresh data will be loaded on next request.",
        }

    @app.post("/admin/rag/reindex")
    async def reindex_rag(
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """
        Force re-index of RAG pipeline (deletes and recreates Qdrant collection).

        Use this endpoint after updating resume.json or other source data to
        refresh the vector search index without restarting the server.

        Authentication:
        - Development: No token required
        - Production: Requires X-Admin-Token header matching ADMIN_TOKEN env var

        Concurrency Protection:
        - Only one reindex operation allowed at a time (prevents wasted API costs)
        - Returns 429 if reindex already in progress

        Returns:
            Operation details including old/new chunk counts and status
        """
        _require_admin(x_admin_token, request)

        # Validate RAG is enabled
        rag_pipeline = get_rag_pipeline()
        if rag_pipeline is None:
            raise HTTPException(
                status_code=503,
                detail="RAG pipeline not initialized (check USE_RAG and API keys in settings).",
            )

        # Prevent concurrent re-indexing (would waste API costs on duplicate embeddings)
        reindex_lock = get_reindex_lock()
        if reindex_lock.locked():
            raise HTTPException(
                status_code=429,
                detail="Re-indexing already in progress. Please wait for it to complete.",
            )

        # Perform re-indexing with async lock protection
        async with reindex_lock:
            try:
                resume_path = settings.data_dir / "resume.json"
                app.state.reindex_status.update(
                    {
                        "running": True,
                        "started_at": time.time(),
                        "finished_at": None,
                        "last_error": None,
                    }
                )
                # Run blocking operation in thread pool (prevents freezing other requests)
                result = await asyncio.to_thread(
                    rag_pipeline.reindex,
                    resume_path,
                    settings.data_dir / "projects",
                )
                app.state.reindex_status.update(
                    {
                        "running": False,
                        "finished_at": time.time(),
                        "last_result": result,
                    }
                )
                # Clear cached resume data so subsequent requests use fresh data
                load_resume_context.cache_clear()
                load_resume_json_public.cache_clear()
                render_llms_text.cache_clear()
                render_resume_pdf.cache_clear()
                _starter_cache.clear()
                logger.info(f"RAG re-index completed: {result['message']}")
                return result
            except Exception as exc:
                logger.exception("Failed to re-index RAG pipeline")
                app.state.reindex_status.update(
                    {
                        "running": False,
                        "finished_at": time.time(),
                        "last_error": str(exc),
                    }
                )
                raise HTTPException(
                    status_code=500,
                    detail=f"Re-indexing failed: {str(exc)}",
                ) from exc

    @app.get("/admin/rag/reindex/status")
    async def reindex_status(
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_admin(x_admin_token, request)
        return app.state.reindex_status

    @app.get("/admin/analytics/export")
    async def export_analytics(
        request: Request,
        x_admin_token: str | None = Header(default=None),
        file: Literal["queries", "feedback"] = "queries",
    ) -> PlainTextResponse:
        """Export analytics data (JSONL). Use ?file=queries or ?file=feedback."""
        _require_admin(x_admin_token, request)
        from analytics.analytics import ANALYTICS_FILE, FEEDBACK_FILE

        path = ANALYTICS_FILE if file == "queries" else FEEDBACK_FILE
        if not path.exists():
            return PlainTextResponse("", media_type="application/jsonl")
        return PlainTextResponse(
            path.read_text(encoding="utf-8"), media_type="application/jsonl"
        )

    @app.get("/api/resume")
    async def get_resume() -> dict:
        """
        Public resume data used to render the sections below the chatbot UI.
        """
        try:
            return load_resume_json_public()
        except RuntimeError as exc:
            logger.exception("Failed to load resume JSON for frontend")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/llms.txt")
    async def llms_txt() -> PlainTextResponse:
        """Machine-readable resume digest (llms.txt convention), rendered
        live from resume.json so it can never drift."""
        try:
            return PlainTextResponse(render_llms_text(), media_type="text/plain; charset=utf-8")
        except RuntimeError as exc:
            logger.exception("Failed to render llms.txt")
            raise HTTPException(status_code=500, detail="Unable to render llms.txt") from exc

    @app.get("/api/resume.pdf")
    async def resume_pdf(request: Request) -> Response:
        """Password-gated PDF download. The chat password (printed on
        Dakota's resume) unlocks the visitor identity via /api/unlock;
        unlocked visitors download a PDF rendered live from resume.json.
        Locked visitors get 403 and the frontend shows the unlock form
        (which mints the visitor cookie itself)."""
        store = get_session_store()
        visitor_id, _ = _resolve_visitor_id(request)

        # Keyed by IP, not visitor: locked visitors may have no cookie yet,
        # and a fresh-minted id every request would never accumulate.
        if not await store.check_rate_limit(f"pdf:{_get_client_ip(request)}", max_requests=5, window=600.0):
            raise HTTPException(
                status_code=429,
                detail="Too many download attempts. Please wait a few minutes.",
            )

        await store.update_metadata(visitor_id)
        unlocked = await store.get_remaining_quota(visitor_id, settings.free_chat_limit) is None
        if not unlocked:
            raise HTTPException(status_code=403, detail=PDF_LOCKED_MESSAGE)

        try:
            pdf_bytes = await asyncio.to_thread(render_resume_pdf)
        except Exception as exc:
            logger.exception("Failed to render resume PDF")
            raise HTTPException(status_code=500, detail="Unable to render the PDF right now.") from exc
        logger.info("Resume PDF downloaded by visitor %s", anonymize_session_id(visitor_id, settings.session_hash_secret))
        final = Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": 'attachment; filename="Dakota-Radigan-Resume.pdf"',
                "Cache-Control": "no-store",
            },
        )
        _set_visitor_cookie(final, visitor_id, settings)
        return final

    @app.post("/api/chat")
    async def chat(payload: ChatRequest, request: Request, response: Response) -> ChatResponse:
        store = get_session_store()
        ctx = await _run_chat_guardrails(payload, request, store, settings)
        session_id, message = ctx.session_id, ctx.message
        today = date.today().isoformat()
        _set_visitor_cookie(response, ctx.visitor_id, settings)

        # Starter question cache: instant responses for suggestion chips.
        # Only used when it's the first message in a session (no history yet).
        cache_key = message.lower().strip().rstrip("?") + "?"
        history = await store.get_history(session_id)
        if not history and cache_key in _starter_cache:
            reply_text = _starter_cache[cache_key]
            await store.append_message(session_id, "user", message)
            await store.append_message(session_id, "assistant", reply_text)
            await asyncio.to_thread(
                log_query,
                anonymize_session_id(session_id, settings.session_hash_secret),
                message,
                reply_text,
            )
            return ChatResponse(reply=reply_text, session_id=session_id)

        client = _make_anthropic_client(settings)
        try:
            system_message, used_rag, sources, model_id, route_reason = (
                await _prepare_generation(message, get_rag_pipeline(), client, settings)
            )
        except RuntimeError as exc:
            logger.exception("Failed to load prompt or resume data")
            await store.release_daily_conversation(today)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        # Same routed-model fallback as the streaming path: a failure on the
        # cheaper model retries once on the known-good primary model.
        candidate_models = [model_id]
        if model_id != settings.anthropic_model:
            candidate_models.append(settings.anthropic_model)

        try:
            api_response = None
            for attempt_index, attempt_model in enumerate(candidate_models):
                try:
                    api_response = await client.messages.create(
                        model=attempt_model,
                        max_tokens=settings.anthropic_max_tokens,
                        **_sampling_kwargs(attempt_model, 0.1),
                        system=system_message,
                        messages=_build_api_messages(history, message),
                    )
                    model_id = attempt_model
                    break
                except AnthropicError:
                    if attempt_index + 1 >= len(candidate_models):
                        raise
                    logger.warning(
                        "Routed model %s failed; falling back to primary model",
                        attempt_model,
                    )
            reply_text = "".join(
                block.text for block in api_response.content if block.type == "text"
            )
        except RateLimitError as exc:
            logger.warning("Anthropic rate limit or spending cap hit")
            await store.release_daily_conversation(today)
            raise HTTPException(status_code=503, detail=BUSY_MESSAGE) from exc
        except AnthropicError as exc:
            logger.exception("Anthropic API request failed after retries")
            await store.release_daily_conversation(today)
            raise HTTPException(status_code=502, detail=GENERIC_CHAT_ERROR) from exc
        except Exception as exc:  # pragma: no cover - unexpected errors
            logger.exception("Unexpected error during chat request")
            await store.release_daily_conversation(today)
            raise HTTPException(
                status_code=500,
                detail="An unexpected error occurred. Please try again.",
            ) from exc

        if not reply_text:
            reply_text = (
                "I couldn't generate a response just now. "
                "Please try asking in a different way."
            )
        reply_text, _ = _split_followups(reply_text)

        await _persist_chat(
            store, settings, session_id, message, reply_text,
            history_was_empty=not history, cache_key=cache_key,
            model_id=model_id, route_reason=route_reason,
        )

        return ChatResponse(
            reply=reply_text, session_id=session_id,
            sources=[s["title"] for s in sources], used_rag=used_rag,
        )

    @app.post("/api/chat/stream")
    async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
        """SSE chat: real pipeline events (retrieval, routing) then token deltas.

        All guardrails raise plain HTTPExceptions BEFORE the stream starts, so
        the frontend's 403-unlock and error handling work exactly as for
        /api/chat. Only failures after headers are sent become `error` events.
        """
        store = get_session_store()
        ctx = await _run_chat_guardrails(payload, request, store, settings)
        session_id, message = ctx.session_id, ctx.message
        today = date.today().isoformat()

        cache_key = message.lower().strip().rstrip("?") + "?"
        history = await store.get_history(session_id)
        cached_reply = _starter_cache.get(cache_key) if not history else None
        quota_remaining = await store.get_remaining_quota(
            ctx.visitor_id, settings.free_chat_limit
        )

        async def event_gen() -> AsyncIterator[str]:
            yield _sse("session", {"session_id": session_id})

            if cached_reply is not None:
                yield _sse("status", {"stage": "cached", "state": "done"})
                yield _sse("delta", {"text": cached_reply})
                await store.append_message(session_id, "user", message)
                await store.append_message(session_id, "assistant", cached_reply)
                await asyncio.to_thread(
                    log_query,
                    anonymize_session_id(session_id, settings.session_hash_secret),
                    message,
                    cached_reply,
                )
                yield _sse("done", {
                    "reply": cached_reply, "used_rag": False, "sources": [],
                    "session_id": session_id, "model": "", "followups": [],
                    "quota_remaining": quota_remaining,
                })
                return

            yield _sse("status", {"stage": "rag_search", "state": "start"})
            client = _make_anthropic_client(settings)
            try:
                system_message, used_rag, sources, model_id, route_reason = (
                    await _prepare_generation(message, get_rag_pipeline(), client, settings)
                )
            except RuntimeError:
                logger.exception("Failed to load prompt or resume data")
                await store.release_daily_conversation(today)
                yield _sse("error", {"detail": GENERIC_CHAT_ERROR})
                return
            yield _sse("status", {
                "stage": "rag_search", "state": "done",
                "used_rag": used_rag, "sources": sources,
            })
            yield _sse("status", {
                "stage": "routing", "state": "done",
                "model": _model_short_label(model_id), "reason": route_reason,
            })
            yield _sse("status", {"stage": "generation", "state": "start"})

            # Resilience: if the routed (cheaper) model fails — e.g. the org's
            # API key lacks access to it — retry once on the primary model,
            # which is the known-good pre-router path. Only retry when no
            # tokens have streamed yet, so text is never duplicated.
            candidate_models = [model_id]
            if model_id != settings.anthropic_model:
                candidate_models.append(settings.anthropic_model)

            try:
                final = None
                used_model = model_id
                for attempt_index, attempt_model in enumerate(candidate_models):
                    streamed_any = False
                    try:
                        async with client.messages.stream(
                            model=attempt_model,
                            max_tokens=settings.anthropic_max_tokens,
                            **_sampling_kwargs(attempt_model, 0.1),
                            system=system_message,
                            messages=_build_api_messages(history, message),
                        ) as stream:
                            async for text in stream.text_stream:
                                streamed_any = True
                                yield _sse("delta", {"text": text})
                            final = await stream.get_final_message()
                        used_model = attempt_model
                        break
                    except AnthropicError:
                        is_last = attempt_index + 1 >= len(candidate_models)
                        if is_last or streamed_any:
                            raise
                        logger.warning(
                            "Routed model %s failed; falling back to primary model",
                            attempt_model,
                        )

                reply_text = "".join(
                    block.text for block in final.content if block.type == "text"
                )
                if not reply_text:
                    reply_text = (
                        "I couldn't generate a response just now. "
                        "Please try asking in a different way."
                    )
                reply_text, followups = _split_followups(reply_text)

                await _persist_chat(
                    store, settings, session_id, message, reply_text,
                    history_was_empty=not history, cache_key=cache_key,
                    model_id=used_model, route_reason=route_reason,
                )
                yield _sse("done", {
                    "reply": reply_text, "used_rag": used_rag, "sources": sources,
                    "session_id": session_id, "model": _model_short_label(used_model),
                    "followups": followups, "quota_remaining": quota_remaining,
                })
            except asyncio.CancelledError:
                # Client disconnected: close the upstream Anthropic stream (the
                # async with does this on unwind), return the reserved daily
                # unit, and skip all persistence.
                logger.info("Client disconnected mid-stream; skipping persistence")
                await store.release_daily_conversation(today)
                raise
            except RateLimitError:
                logger.warning("Anthropic rate limit or spending cap hit")
                await store.release_daily_conversation(today)
                yield _sse("error", {"detail": BUSY_MESSAGE})
            except AnthropicError:
                logger.exception("Anthropic API request failed after retries")
                await store.release_daily_conversation(today)
                yield _sse("error", {"detail": GENERIC_CHAT_ERROR})
            except Exception:  # pragma: no cover - unexpected errors
                logger.exception("Unexpected error during streamed chat")
                await store.release_daily_conversation(today)
                yield _sse("error", {"detail": "An unexpected error occurred. Please try again."})

        streaming_response = StreamingResponse(
            event_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
        _set_visitor_cookie(streaming_response, ctx.visitor_id, settings)
        return streaming_response

    @app.post("/api/jd-match")
    async def jd_match(payload: JDMatchRequest, request: Request) -> StreamingResponse:
        """SSE job-fit analysis for a pasted job description.

        Draws from its own daily budget (jd_daily_limit) so it never consumes
        the chat quota; password unlock bypasses it. The pasted JD is untrusted:
        delimiter tags are stripped and it rides in the user turn only. Briefs
        are quota-free but require a prior analysis in this session.
        """
        store = get_session_store()
        guard_payload = ChatRequest(message=payload.jd_text, session_id=payload.session_id)
        ctx = await _run_chat_guardrails(
            guard_payload, request, store, settings,
            max_chars=settings.max_jd_chars, consume_quota=False,
        )
        session_id = ctx.session_id
        today = date.today().isoformat()

        async def _reject(exc: HTTPException) -> None:
            # Return the daily unit reserved in the guardrails.
            await store.release_daily_conversation(today)
            raise exc

        # Token-heavy endpoint: extra per-IP limit on top of the global one
        jd_rate_key = f"jd:{_get_client_ip(request)}"
        if not await store.check_rate_limit(jd_rate_key, max_requests=3, window=600.0):
            await _reject(HTTPException(
                status_code=429,
                detail="Too many fit analyses at once. Please wait a few minutes and try again.",
            ))

        history = await store.get_history(session_id)

        if payload.mode == "brief":
            has_analysis = any(
                JD_SENTINEL in block.get("text", "")
                for msg in history
                if msg.get("role") == "user"
                for block in msg.get("content", [])
                if isinstance(block, dict)
            )
            if not has_analysis:
                await _reject(HTTPException(status_code=409, detail="Run a fit analysis first."))
        jd_unit_reserved = False
        if payload.mode != "brief":
            # Unlimited (password-unlocked) identities bypass the JD budget.
            remaining = await store.get_remaining_quota(
                ctx.visitor_id, settings.free_chat_limit
            )
            if remaining is not None:
                allowed = await store.check_and_increment_scoped_limit(
                    ctx.visitor_id, "jd", settings.jd_daily_limit, today
                )
                if not allowed:
                    await _reject(HTTPException(status_code=403, detail=JD_LIMIT_MESSAGE))
                jd_unit_reserved = True

        async def _release_budgets() -> None:
            # A failed or cancelled generation must return BOTH budget units —
            # the global daily reservation and, when one was taken, the
            # visitor's JD unit. Nobody loses their free analysis to a 529.
            await store.release_daily_conversation(today)
            if jd_unit_reserved:
                await store.release_scoped_limit(ctx.visitor_id, "jd", today)

        sanitized = _sanitize_jd_text(ctx.message)
        if payload.mode == "brief":
            user_text = (
                "Generate a phone-screen brief for the role analyzed above: "
                "suggested screening questions with answers grounded in the "
                "resume, key logistics, and the recruiter summary, as one "
                "copyable block."
            )
            stored_user_text = "[jd-brief] requested"
        else:
            user_text = (
                "Analyze Dakota's fit for this role.\n"
                f"<job_description>\n{sanitized}\n</job_description>"
            )
            stored_user_text = f"{JD_SENTINEL} {sanitized[:300]}"

        async def event_gen() -> AsyncIterator[str]:
            yield _sse("session", {"session_id": session_id})
            yield _sse("status", {"stage": "context_load", "state": "start"})
            try:
                system_message = (
                    f"{load_system_prompt()}\n\n{load_jd_match_prompt()}"
                    f"\n\n[RESUME DATA]\n{load_resume_context()}"
                )
            except RuntimeError:
                logger.exception("Failed to load prompt or resume data")
                await _release_budgets()
                yield _sse("error", {"detail": GENERIC_CHAT_ERROR})
                return
            yield _sse("status", {"stage": "context_load", "state": "done"})
            yield _sse("status", {"stage": "generation", "state": "start"})

            # Always the primary model: JD analysis is the synthesis-heavy case.
            client = _make_anthropic_client(settings)
            try:
                async with client.messages.stream(
                    model=settings.anthropic_model,
                    max_tokens=settings.anthropic_max_tokens,
                    **_sampling_kwargs(settings.anthropic_model, 0.1),
                    system=system_message,
                    messages=_build_api_messages(history, user_text),
                ) as stream:
                    async for text in stream.text_stream:
                        yield _sse("delta", {"text": text})
                    final = await stream.get_final_message()

                reply_text = "".join(
                    block.text for block in final.content if block.type == "text"
                )
                if not reply_text:
                    reply_text = (
                        "I couldn't generate the analysis just now. "
                        "Please try again."
                    )
                reply_text, _ = _split_followups(reply_text)

                await _persist_chat(
                    store, settings, session_id, stored_user_text, reply_text,
                    history_was_empty=False, cache_key="",
                    model_id=settings.anthropic_model, route_reason="jd-match",
                )
                yield _sse("done", {
                    "reply": reply_text, "mode": payload.mode,
                    "session_id": session_id, "used_rag": False, "sources": [],
                    "followups": [], "quota_remaining": None,
                })
            except asyncio.CancelledError:
                logger.info("Client disconnected mid-analysis; skipping persistence")
                await _release_budgets()
                raise
            except RateLimitError:
                logger.warning("Anthropic rate limit or spending cap hit")
                await _release_budgets()
                yield _sse("error", {"detail": BUSY_MESSAGE})
            except AnthropicError:
                logger.exception("Anthropic API request failed after retries")
                await _release_budgets()
                yield _sse("error", {"detail": GENERIC_CHAT_ERROR})
            except Exception:  # pragma: no cover - unexpected errors
                logger.exception("Unexpected error during JD analysis")
                await _release_budgets()
                yield _sse("error", {"detail": "An unexpected error occurred. Please try again."})

        streaming_response = StreamingResponse(
            event_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
        _set_visitor_cookie(streaming_response, ctx.visitor_id, settings)
        return streaming_response

    @app.post("/api/unlock")
    async def unlock_chat(
        payload: UnlockRequest, request: Request, response: Response
    ) -> UnlockResponse:
        """
        Unlock unlimited chat access with password.
        Password is found on Dakota's resume PDF.

        Unlock is granted to the server-minted visitor identity, so it
        survives cleared localStorage and new session ids. This may be the
        visitor's first request — the cookie is minted and set here too.
        """
        store = get_session_store()
        visitor_id, _ = _resolve_visitor_id(request)
        _set_visitor_cookie(response, visitor_id, settings)

        # Rate limit brute-force attempts per IP AND per visitor identity
        # (5 per minute each).
        ip_allowed = await store.check_rate_limit(
            f"unlock:{_get_client_ip(request)}", max_requests=5, window=60.0
        )
        visitor_allowed = await store.check_rate_limit(
            f"unlock:visitor:{visitor_id}", max_requests=5, window=60.0
        )
        if not (ip_allowed and visitor_allowed):
            return UnlockResponse(
                success=False,
                message="Too many attempts. Please wait a moment and try again."
            )

        # Check if password is configured
        if not settings.chat_password:
            return UnlockResponse(
                success=False,
                message="Chat password not configured."
            )

        # Verify password (case-insensitive, constant-time comparison)
        provided = payload.password.strip().lower()
        if not provided or not hmac.compare_digest(provided, settings.chat_password.lower()):
            return UnlockResponse(
                success=False,
                message="Incorrect password. Please check Dakota's resume."
            )

        # Grant unlimited access to the visitor identity
        await store.update_metadata(visitor_id)
        await store.set_unlimited(visitor_id, True)

        return UnlockResponse(
            success=True,
            message="Unlimited chat access granted! Continue the conversation."
        )

    @app.post("/api/feedback")
    async def submit_feedback(payload: FeedbackRequest, request: Request):
        """Log user feedback (thumbs up/down)."""
        store = get_session_store()

        # Rate limit: prevent unbounded writes to the feedback log
        rate_limit_key = f"feedback:{_get_client_ip(request)}"
        allowed = await store.check_rate_limit(rate_limit_key, max_requests=10, window=60.0)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too much feedback at once. Please wait a moment and try again.",
            )

        await asyncio.to_thread(
            log_feedback,
            anonymize_session_id(payload.session_id, settings.session_hash_secret),
            payload.rating,
            payload.comment,
            payload.trigger
        )
        return {"success": True}

    # MCP endpoint (streamable HTTP), registered before the "/" static
    # catch-all. The SDK's Starlette sub-app holds a single ASGI route;
    # re-root it at /mcp directly — a Mount would 405 bare `POST /mcp`
    # (empty-remainder mounts can only slash-redirect GETs). Data-only —
    # see _build_mcp_server.
    class _McpOrBrowser:
        """ASGI wrapper (a class instance so Starlette treats it as an ASGI
        app, not a GET-only request handler). A human opening /mcp in a
        browser would get a bare JSON-RPC "Not Acceptable" error; send them
        to the connect instructions instead. Real MCP clients GET with
        Accept: text/event-stream."""

        def __init__(self, endpoint: Any) -> None:
            self.endpoint = endpoint

        async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
            if scope["type"] == "http" and scope.get("method") == "GET":
                accept = next(
                    (v.decode() for k, v in scope.get("headers", []) if k == b"accept"), ""
                )
                if "text/event-stream" not in accept:
                    redirect = RedirectResponse(
                        "/how-it-works.html#connect-mcp", status_code=302
                    )
                    await redirect(scope, receive, send)
                    return
            await self.endpoint(scope, receive, send)

    app.router.routes.append(
        StarletteRoute("/mcp", endpoint=_McpOrBrowser(mcp_asgi_app.routes[0].endpoint), name="mcp")
    )

    # Serve the frontend files from ../frontend
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount(
            "/",
            StaticFiles(directory=frontend_dir, html=True),
            name="frontend",
        )

    return app


app = build_app()

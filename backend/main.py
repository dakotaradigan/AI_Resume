from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from functools import lru_cache
from typing import Any
from uuid import uuid4

from anthropic import AsyncAnthropic, AnthropicError
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.staticfiles import StaticFiles

from config import get_settings
from rag import initialize_rag_pipeline, RAGPipeline

logger = logging.getLogger("resume-assistant")

# Keep context small: compact early and keep fewer turns to reduce memory and token use.
MAX_SESSION_MESSAGES = 24
COMPACT_AFTER = 12
COMPACT_KEEP_RECENT = 10
COMPACT_CHAR_LIMIT = 800

# Scalability: In-memory storage (easy to swap to Redis later)
# Wrapped in SessionStore class for async-safe access
class SessionStore:
    """
    Thread-safe session storage for async FastAPI.

    Wraps session messages, metadata, and rate limits with asyncio.Lock()
    to prevent race conditions when multiple coroutines access the same session.

    Migration path: Replace internal dicts with Redis when scaling to multiple workers.
    """

    def __init__(self):
        self._messages: dict[str, list[dict]] = {}
        self._metadata: dict[str, dict] = {}
        self._rate_limits: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def get_history(self, session_id: str) -> list[dict]:
        """Get session history, creating empty list if needed."""
        async with self._lock:
            if session_id not in self._messages:
                self._messages[session_id] = []
            return self._messages[session_id]

    async def set_history(self, session_id: str, history: list[dict]) -> None:
        """Replace session history (used after compaction)."""
        async with self._lock:
            self._messages[session_id] = history

    async def append_message(self, session_id: str, role: str, text: str) -> None:
        """Append a message to session history."""
        async with self._lock:
            if session_id not in self._messages:
                self._messages[session_id] = []
            self._messages[session_id].append({
                "role": role,
                "content": [{"type": "text", "text": text}]
            })

    async def update_metadata(self, session_id: str) -> None:
        """Track session creation and last access time for cleanup."""
        async with self._lock:
            now = time.time()
            if session_id not in self._metadata:
                self._metadata[session_id] = {"created_at": now, "last_access": now}
            else:
                self._metadata[session_id]["last_access"] = now

    async def check_rate_limit(self, key: str, max_requests: int, window: float = 60.0) -> bool:
        """
        Check if request is within rate limit.
        Returns True if allowed, False if limit exceeded.
        """
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

    async def cleanup_expired(self, max_age_seconds: int) -> int:
        """
        Remove sessions older than max_age_seconds.
        Returns count of cleaned sessions.
        """
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
        async with self._lock:
            now = time.time()
            stale_cutoff = now - (window * 2)
            stale_keys = [
                key for key, timestamps in self._rate_limits.items()
                if timestamps and timestamps[-1] < stale_cutoff
            ]
            for key in stale_keys:
                self._rate_limits.pop(key, None)


# Global session store instance
_session_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    """Get or create the global session store."""
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
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
    """
    Best-effort client IP extraction.
    If behind a proxy, ensure it sets X-Forwarded-For (and that you trust it).
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # Take the left-most IP (original client) per convention.
        ip = xff.split(",")[0].strip()
        if ip:
            return ip
    return request.client.host if request.client else "unknown"


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str


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


def retrieve_rag_context(
    rag_pipeline: RAGPipeline | None,
    query: str,
    limit: int = 3,
    score_threshold: float = 0.5
) -> tuple[str, bool]:
    """
    Retrieve relevant resume context using RAG pipeline.

    Args:
        rag_pipeline: Initialized RAG pipeline (None if disabled)
        query: User's message to search for relevant context
        limit: Maximum number of chunks to retrieve
        score_threshold: Minimum similarity score (0-1)

    Returns:
        (context, used_rag) where used_rag indicates whether retrieved chunks were used.
    """
    if rag_pipeline is None:
        logger.warning("RAG pipeline not initialized, falling back to static context")
        return load_resume_context(), False

    try:
        results = rag_pipeline.search(query, limit=limit, score_threshold=score_threshold)

        if not results:
            logger.info(f"No RAG results found for query (threshold={score_threshold}), using static context")
            return load_resume_context(), False

        # Format retrieved chunks into context string
        context_parts = []
        for idx, result in enumerate(results, 1):
            context_parts.append(
                f"[Context {idx}: {result['title']}]\n{result['text']}"
            )

        return "\n\n".join(context_parts), True

    except Exception as exc:
        logger.exception("RAG retrieval failed, falling back to static context")
        return load_resume_context(), False


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
    summary_message = {
        "role": "system",
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
        )
        logger.info("✅ RAG pipeline initialized successfully")
        return pipeline

    except Exception as exc:
        logger.exception("Failed to initialize RAG pipeline, falling back to static context")
        return None


def build_app() -> FastAPI:
    app = FastAPI(title="Resume Assistant")
    settings = get_settings()
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
        # TODO: Update with your production domain before deploying
        allowed_origins = [
            "https://assistant.dakotaradigan.com",
            "https://dakotaradigan.com",
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

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    def get_rag_pipeline() -> RAGPipeline | None:
        """FastAPI dependency that returns the initialized RAG pipeline."""
        return getattr(app.state, "rag_pipeline", None)

    def _require_admin(x_admin_token: str | None) -> None:
        if settings.admin_token:
            if x_admin_token != settings.admin_token:
                raise HTTPException(status_code=401, detail="Unauthorized.")
            return
        if settings.environment != "development":
            raise HTTPException(
                status_code=503,
                detail="Admin endpoint disabled (ADMIN_TOKEN not configured).",
            )

    @app.get("/health/rag")
    async def rag_health() -> dict[str, str | bool]:
        """Check RAG pipeline status for debugging and monitoring."""
        rag_pipeline = get_rag_pipeline()
        return {
            "rag_enabled": settings.use_rag,
            "rag_initialized": rag_pipeline is not None,
            "openai_key_configured": bool(settings.openai_api_key),
            "qdrant_url": settings.qdrant_url or "",
            "qdrant_api_key_configured": bool(settings.qdrant_api_key),
        }

    @app.post("/admin/cache/clear")
    async def clear_cache(x_admin_token: str | None = Header(default=None)) -> dict[str, str]:
        """
        Clear all cached data (system prompt, resume context).

        Use this endpoint after updating resume.json or system_prompt.txt
        to refresh the cache without restarting the server.

        Note: In production, this endpoint should be protected with authentication.
        """
        _require_admin(x_admin_token)

        load_system_prompt.cache_clear()
        load_resume_context.cache_clear()
        load_resume_json_public.cache_clear()
        logger.info("Cache cleared: system_prompt and resume_context")
        return {
            "status": "success",
            "message": "Cache cleared. Fresh data will be loaded on next request.",
        }

    @app.post("/admin/rag/reindex")
    async def reindex_rag(x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
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
        _require_admin(x_admin_token)

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
                result = await asyncio.to_thread(rag_pipeline.reindex, resume_path)
                app.state.reindex_status.update(
                    {
                        "running": False,
                        "finished_at": time.time(),
                        "last_result": result,
                    }
                )
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
    async def reindex_status(x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
        _require_admin(x_admin_token)
        return app.state.reindex_status

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

    @app.post("/api/chat")
    async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
        session_id = payload.session_id or str(uuid4())
        store = get_session_store()

        # === Scalability Guardrails ===

        # 1. Session cleanup: Remove old sessions periodically
        expired_count = await store.cleanup_expired(settings.session_max_age_seconds)
        if expired_count > 0:
            logger.info(f"Cleaned up {expired_count} expired sessions")
        await store.cleanup_stale_rate_limits()

        # 2. Update session metadata (tracks last access for cleanup)
        await store.update_metadata(session_id)

        # 3. Rate limiting: Prevent abuse (default key = client IP)
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

        # === Validation ===

        # Input bounds
        message = (payload.message or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="Message cannot be empty.")
        if len(message) > settings.max_user_message_chars:
            raise HTTPException(
                status_code=413,
                detail=f"Message too long (max {settings.max_user_message_chars} characters).",
            )

        if not settings.anthropic_api_key:
            raise HTTPException(
                status_code=503,
                detail="Anthropic API key not configured. Set ANTHROPIC_API_KEY.",
            )

        try:
            system_prompt = load_system_prompt()

            # Use RAG retrieval if enabled, otherwise fall back to static context
            rag_pipeline = get_rag_pipeline()
            if settings.use_rag and rag_pipeline is not None:
                resume_context, used_rag = retrieve_rag_context(
                    rag_pipeline,
                    message,
                    limit=3,
                    score_threshold=0.5
                )
                context_label = "RETRIEVED CONTEXT" if used_rag else "RESUME DATA"
            else:
                resume_context = load_resume_context()
                context_label = "RESUME DATA"

        except RuntimeError as exc:
            logger.exception("Failed to load prompt or resume data")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        system_message = f"{system_prompt}\n\n[{context_label}]\n{resume_context}"

        # === Async API Call with Timeout and Retry ===

        # 4. API timeout and automatic retry: Prevent hanging requests and handle transient failures
        # Using async client to avoid blocking the event loop under high load
        client = AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.api_timeout_seconds,
            max_retries=3,  # Built-in retry with exponential backoff
        )

        try:
            history = await store.get_history(session_id)
            messages = [
                *history,
                {"role": "user", "content": [{"type": "text", "text": message}]},
            ]

            response = await client.messages.create(
                model=settings.anthropic_model,
                max_tokens=settings.anthropic_max_tokens,
                temperature=0.1,  # Low temperature for factual accuracy
                system=system_message,
                messages=messages,
            )
            reply_text = "".join(
                block.text for block in response.content if block.type == "text"
            )
        except AnthropicError as exc:
            logger.exception("Anthropic API request failed after retries")
            raise HTTPException(
                status_code=502,
                detail="Unable to process chat right now. Please try again soon.",
            ) from exc
        except Exception as exc:  # pragma: no cover - unexpected errors
            logger.exception("Unexpected error during chat request")
            raise HTTPException(
                status_code=500,
                detail="An unexpected error occurred. Please try again.",
            ) from exc

        if not reply_text:
            reply_text = (
                "I couldn't generate a response just now. "
                "Please try asking in a different way."
            )

        # Append messages and compact history
        await store.append_message(session_id, "user", message)
        await store.append_message(session_id, "assistant", reply_text)
        await _compact_session_history(session_id, store)

        return ChatResponse(reply=reply_text, session_id=session_id)

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

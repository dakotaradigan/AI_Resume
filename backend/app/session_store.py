"""Async-safe session, quota, and rate-limit storage.

In-memory by default (single process); Redis-backed when ``REDIS_URL`` is set,
which shares sessions, quotas, and budgets across instances.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import date

from analytics.analytics import anonymize_session_id

from app.config import get_settings
from app.constants import CHAT_LIMIT_MESSAGE

try:
    from redis import asyncio as redis_asyncio
except ImportError:  # pragma: no cover - optional dependency until REDIS_URL is set
    redis_asyncio = None

logger = logging.getLogger(__name__)

# Daily conversation counters keyed by ISO date (in-memory mode only; the Redis
# path uses self-expiring keys).
_daily_conversation_count: dict[str, int] = {}  # {"2026-02-03": 42}


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
                    logger.warning(
                        "Skipping invalid Redis history entry for session %s",
                        anonymize_session_id(session_id, get_settings().session_hash_secret),
                    )
            return history

        async with self._lock:
            if session_id not in self._messages:
                self._messages[session_id] = []
            # Return a copy: callers must not mutate our internal list, and this
            # keeps in-memory semantics aligned with the Redis path (which always
            # returns a freshly-decoded list).
            return list(self._messages[session_id])

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

    async def release_chat_limit(self, session_id: str) -> None:
        """Return a chat-quota unit taken by check_and_increment_limit (floor 0).

        Called when generation fails server-side so a visitor never loses one of
        their few free exchanges to an upstream 5xx — mirrors the daily-budget
        and JD-unit release paths ("nobody loses a turn to a 529").
        """
        if self._redis is not None:
            script = """
            local current = tonumber(redis.call('HGET', KEYS[1], 'user_message_count') or '0')
            if current > 0 then
                redis.call('HINCRBY', KEYS[1], 'user_message_count', -1)
            end
            return 0
            """
            await self._redis.eval(script, 1, self._meta_key(session_id))
            return

        async with self._lock:
            meta = self._metadata.get(session_id)
            if meta:
                count = meta.get("user_message_count", 0)
                if count > 0:
                    meta["user_message_count"] = count - 1

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

    async def mark_jd_analysis(self, session_id: str) -> None:
        """Record that a real JD fit analysis completed for this session.

        Server-owned so brief mode cannot be unlocked by a visitor typing a
        sentinel string into ordinary chat history.
        """
        if self._redis is not None:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.hset(self._meta_key(session_id), "jd_analysis_done", "1")
                pipe.expire(self._meta_key(session_id), self._session_ttl)
                await pipe.execute()
            return

        async with self._lock:
            self._metadata.setdefault(session_id, {})["jd_analysis_done"] = True

    async def has_jd_analysis(self, session_id: str) -> bool:
        """Whether a real JD analysis has completed for this session."""
        if self._redis is not None:
            return await self._redis.hget(
                self._meta_key(session_id), "jd_analysis_done"
            ) == "1"

        async with self._lock:
            return bool(self._metadata.get(session_id, {}).get("jd_analysis_done", False))

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

            # Prune day-keyed counters from past days (the Redis path self-expires
            # via EXPIRE; the in-memory path would otherwise grow one entry per
            # day and per (scope, visitor, day) forever).
            today = date.today().isoformat()
            for counter_key in [k for k in self._scoped_counts if k[2] < today]:
                self._scoped_counts.pop(counter_key, None)
            for day_key in [d for d in _daily_conversation_count if d < today]:
                _daily_conversation_count.pop(day_key, None)

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


# Process-wide store instance (swap to Redis by setting REDIS_URL).
_session_store: SessionStore | None = None


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


def reset_session_store() -> None:
    """Testing hook: drop the process-wide store so the next request builds a fresh one."""
    global _session_store
    _session_store = None

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from functools import lru_cache
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
SESSION_MESSAGES: dict[str, list[dict]] = {}
SESSION_METADATA: dict[str, dict] = {}  # Track creation time, last access
RATE_LIMIT_TRACKER: dict[str, list[float]] = defaultdict(list)  # RateLimitKey -> [timestamps]


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


def _check_rate_limit(rate_limit_key: str) -> bool:
    """
    Rate limiting: Allow max N requests per minute per key (defaults to client IP).
    Returns True if request is allowed, False if rate limit exceeded.

    Migration path: Replace with Redis-based rate limiting when scaling.
    """
    settings = get_settings()
    now = time.time()
    window = 60.0  # 1 minute window

    # Get recent request timestamps for this key
    timestamps = RATE_LIMIT_TRACKER[rate_limit_key]

    # Remove timestamps older than the window
    timestamps[:] = [ts for ts in timestamps if now - ts < window]

    # Check if limit exceeded
    if len(timestamps) >= settings.rate_limit_requests_per_minute:
        return False

    # Add current request timestamp
    timestamps.append(now)
    return True


def _cleanup_rate_limits() -> None:
    """
    Prevent unbounded growth of RATE_LIMIT_TRACKER by deleting keys that haven't
    been used recently.
    """
    now = time.time()
    window = 60.0
    stale_cutoff = now - (window * 2)
    keys = list(RATE_LIMIT_TRACKER.keys())
    for key in keys:
        ts = RATE_LIMIT_TRACKER.get(key)
        if ts and ts[-1] < stale_cutoff:
            RATE_LIMIT_TRACKER.pop(key, None)


def _cleanup_old_sessions() -> None:
    """
    Session cleanup: Remove sessions older than max age to prevent memory leaks.
    Runs on each request (lightweight check).

    Thread-safe: Creates snapshot of session IDs before iteration to avoid
    "dictionary changed size during iteration" errors in concurrent environments.

    Migration path: Use Redis TTL for automatic expiration when scaling.
    """
    settings = get_settings()
    now = time.time()
    max_age = settings.session_max_age_seconds

    # Thread-safe: Create snapshot of session IDs to avoid race conditions
    session_ids = list(SESSION_METADATA.keys())

    # Find expired sessions by checking each ID individually
    expired = []
    for sid in session_ids:
        meta = SESSION_METADATA.get(sid)
        if meta and now - meta.get("last_access", 0) > max_age:
            expired.append(sid)

    # Clean up expired sessions (use .pop() which is atomic for individual operations)
    for sid in expired:
        SESSION_MESSAGES.pop(sid, None)
        SESSION_METADATA.pop(sid, None)

    if expired:
        logger.info(f"Cleaned up {len(expired)} expired sessions")


def _update_session_metadata(session_id: str) -> None:
    """Track session creation and last access time for cleanup."""
    now = time.time()
    if session_id not in SESSION_METADATA:
        SESSION_METADATA[session_id] = {"created_at": now, "last_access": now}
    else:
        SESSION_METADATA[session_id]["last_access"] = now


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
        technical = skills.get("technical", []) or []
        if technical:
            lines.append(f"- Technical: {', '.join(technical)}")

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


def _get_session_history(session_id: str) -> list[dict]:
    history = SESSION_MESSAGES.get(session_id)
    if history is None:
        history = []
        SESSION_MESSAGES[session_id] = history
    return history


def _append_session_message(session_id: str, role: str, text: str) -> None:
    history = _get_session_history(session_id)
    history.append({"role": role, "content": [{"type": "text", "text": text}]})
    _compact_session_history(session_id)


def _compact_session_history(session_id: str) -> None:
    history = _get_session_history(session_id)
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

    SESSION_MESSAGES[session_id] = new_history


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
        if settings.environment != "development":
            if not settings.admin_token:
                raise HTTPException(
                    status_code=503,
                    detail="Admin endpoint disabled (ADMIN_TOKEN not configured).",
                )
            if x_admin_token != settings.admin_token:
                raise HTTPException(status_code=401, detail="Unauthorized.")

        load_system_prompt.cache_clear()
        load_resume_context.cache_clear()
        logger.info("Cache cleared: system_prompt and resume_context")
        return {
            "status": "success",
            "message": "Cache cleared. Fresh data will be loaded on next request.",
        }

    @app.post("/api/chat")
    async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
        session_id = payload.session_id or str(uuid4())

        # === Scalability Guardrails ===

        # 1. Session cleanup: Remove old sessions periodically
        _cleanup_old_sessions()
        _cleanup_rate_limits()

        # 2. Update session metadata (tracks last access for cleanup)
        _update_session_metadata(session_id)

        # 3. Rate limiting: Prevent abuse (default key = client IP)
        rate_limit_key = _get_client_ip(request)
        if not _check_rate_limit(rate_limit_key):
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
            history = _get_session_history(session_id)
            messages = [
                *history,
                {"role": "user", "content": [{"type": "text", "text": message}]},
            ]

            response = await client.messages.create(
                model=settings.anthropic_model,
                max_tokens=settings.anthropic_max_tokens,
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

        _append_session_message(session_id, "user", message)
        _append_session_message(session_id, "assistant", reply_text)

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


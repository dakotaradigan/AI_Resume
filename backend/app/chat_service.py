"""Shared chat-turn logic: guardrails, context building, persistence, SSE.

Used by /api/chat, /api/chat/stream, and /api/jd-match so quota accounting and
error handling stay identical across endpoints.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import uuid4

from analytics.analytics import anonymize_session_id, log_query
from anthropic import AsyncAnthropic
from fastapi import HTTPException, Request
from rag import RAGPipeline

from app.config import Settings
from app.constants import BUSY_MESSAGE, IP_DAILY_LIMIT_MESSAGE
from app.content import load_resume_context, load_system_prompt
from app.identity import get_client_ip, resolve_visitor_id
from app.llm import route_model
from app.retrieval import retrieve_rag_context
from app.schemas import ChatRequest
from app.session_store import SessionStore

logger = logging.getLogger(__name__)

# Keep context small: compact early and keep fewer turns to reduce memory and token use.
MAX_SESSION_MESSAGES = 24
COMPACT_AFTER = 12
COMPACT_KEEP_RECENT = 10
COMPACT_CHAR_LIMIT = 800

# The system prompt asks the model to end replies with a machine-readable
# follow-up line: "FOLLOWUPS: q1 | q2 | q3". It is stripped from every stored,
# cached, and returned reply; the parsed questions ride on the SSE done event.
FOLLOWUPS_MARKER = "FOLLOWUPS:"

# Pre-cached responses for starter suggestion chips (populated lazily on first hit).
# Key = lowercased/stripped question text, Value = cached reply string.
_starter_cache: dict[str, str] = {}
# Entries must end with "?" to match starter_cache_key's normalization.
STARTER_QUESTIONS = frozenset({
    "what's dakota's background?",
    "tell me about dakota's ai projects?",
    "what can dakota do for my company?",
    "how was this site built?",
})


def split_followups(reply_text: str) -> tuple[str, list[str]]:
    """Split the trailing FOLLOWUPS marker line off a model reply."""
    lines = reply_text.rstrip().split("\n")
    if lines and lines[-1].strip().startswith(FOLLOWUPS_MARKER):
        raw = lines[-1].strip()[len(FOLLOWUPS_MARKER):]
        followups = [q.strip() for q in raw.split("|") if q.strip()][:3]
        return "\n".join(lines[:-1]).rstrip(), followups
    return reply_text, []


def starter_cache_key(message: str) -> str:
    return message.lower().strip().rstrip("?") + "?"


def get_cached_starter(cache_key: str) -> str | None:
    return _starter_cache.get(cache_key)


def cache_starter_reply(cache_key: str, reply_text: str) -> None:
    if cache_key in STARTER_QUESTIONS:
        _starter_cache[cache_key] = reply_text


def clear_starter_cache() -> None:
    _starter_cache.clear()


def sse(event: str, data: dict[str, Any]) -> str:
    """Format one SSE frame. json.dumps guarantees single-line data."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@dataclass(frozen=True)
class ChatTurnContext:
    """Validated identity + input for one chat turn."""

    session_id: str
    visitor_id: str
    message: str


async def run_chat_guardrails(
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
    visitor_id, _ = resolve_visitor_id(request, settings)

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
    rate_limit_key = get_client_ip(request, settings)
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

    # Hard per-IP daily cap on token-spending requests. Keyed to the client IP,
    # so it survives dropping/rotating the visitor cookie — no single IP can
    # drain the global daily budget. Password-unlocked (unlimited) visitors
    # bypass it, so unrestricted token use requires the password. Only enforced
    # when the real client IP is trusted (trust_proxy_headers); otherwise every
    # visitor collapses to the proxy IP and the cap would lock out the whole
    # site, so it fails open to the pre-existing behavior.
    if settings.per_ip_daily_limit > 0 and settings.trust_proxy_headers:
        unlimited = (
            await store.get_remaining_quota(visitor_id, settings.free_chat_limit)
            is None
        )
        if not unlimited:
            within_ip_cap = await store.check_and_increment_scoped_limit(
                rate_limit_key, "ip", settings.per_ip_daily_limit, today
            )
            if not within_ip_cap:
                # Refund the chat unit just consumed so an IP-capped request
                # charges neither the visitor's free quota nor the daily budget.
                if consume_quota:
                    await store.release_chat_limit(visitor_id)
                await _reject(
                    HTTPException(status_code=403, detail=IP_DAILY_LIMIT_MESSAGE)
                )

    return ChatTurnContext(session_id=session_id, visitor_id=visitor_id, message=message)


async def compact_session_history(session_id: str, store: SessionStore) -> None:
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


def build_chat_context(
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


async def prepare_generation(
    message: str,
    rag_pipeline: RAGPipeline | None,
    client: AsyncAnthropic,
    settings: Settings,
) -> tuple[str, bool, list[dict[str, Any]], str, str]:
    """Run context retrieval and model routing concurrently (routing must not
    add serial time-to-first-token)."""
    (system_message, used_rag, sources), (model_id, route_reason) = await asyncio.gather(
        asyncio.to_thread(build_chat_context, message, rag_pipeline, settings),
        route_model(message, client, settings),
    )
    return system_message, used_rag, sources, model_id, route_reason


async def persist_chat(
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
    cacheable: bool = True,
) -> None:
    """Post-generation bookkeeping. reply_text must already be FOLLOWUPS-stripped.
    (The daily budget was reserved up front in the guardrails.)"""
    # Cache response for starter questions (populate lazily on first real answer).
    # cacheable is False when reply_text is a canned error/empty-response fallback,
    # so a transient blip on the first click never latches as the chip's answer.
    if cacheable and history_was_empty:
        cache_starter_reply(cache_key, reply_text)

    await store.append_message(session_id, "user", message)
    await store.append_message(session_id, "assistant", reply_text)
    await compact_session_history(session_id, store)

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


async def persist_cached_reply(
    store: SessionStore,
    settings: Settings,
    session_id: str,
    message: str,
    reply_text: str,
) -> None:
    """Persist a starter-cache hit: history plus analytics, no model metadata."""
    await store.append_message(session_id, "user", message)
    await store.append_message(session_id, "assistant", reply_text)
    await asyncio.to_thread(
        log_query,
        anonymize_session_id(session_id, settings.session_hash_secret),
        message,
        reply_text,
    )


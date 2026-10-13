"""Shared chat-turn logic: guardrails, context building, persistence, SSE.

Used by /api/chat, /api/chat/stream, /api/jd-match and the MCP tools so quota
accounting and error handling stay identical across every entry point.
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
from anthropic import AnthropicError, AsyncAnthropic, RateLimitError
from fastapi import HTTPException, Request
from rag import RAGPipeline

from app.config import Settings
from app.constants import BUSY_MESSAGE, GENERIC_CHAT_ERROR, IP_DAILY_LIMIT_MESSAGE
from app.content import load_resume_context, load_system_prompt
from app.identity import get_client_ip, resolve_visitor_id
from app.llm import (
    build_api_messages,
    estimate_cost_usd,
    make_anthropic_client,
    route_model,
    sampling_kwargs,
    system_blocks,
    usage_record,
)
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

EMPTY_REPLY_FALLBACK = (
    "I couldn't generate a response just now. "
    "Please try asking in a different way."
)
UNEXPECTED_ERROR_MESSAGE = "An unexpected error occurred. Please try again."

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
    visitor_id: str | None = None,
) -> ChatTurnContext:
    """Run every pre-generation guardrail. Raises HTTPException before any
    stream starts, so error handling is identical for both chat endpoints.

    ``visitor_id`` overrides the cookie identity for callers that hold no
    cookies (the MCP tools derive one from the client IP)."""
    session_id = payload.session_id or str(uuid4())
    if visitor_id is None:
        visitor_id, _ = resolve_visitor_id(request, settings)

    # Session cleanup: remove old sessions periodically
    expired_count = await store.cleanup_expired(settings.session_max_age_seconds)
    if expired_count > 0:
        logger.info(f"Cleaned up {expired_count} expired sessions")
    await store.cleanup_stale_rate_limits()

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

    # Identity rows are written only now, for a request that passed the rate
    # limit, the daily reservation and the input bounds. A refused request
    # leaves nothing behind, so a client cannot grow the store by sending
    # requests that will never be answered (two rows per request used to be
    # written before any check ran). The visitor row must be refreshed before
    # the quota check below reads it: its metadata carries quota/unlock state,
    # and without a fresh last_access, cleanup_expired would wipe it and reset
    # the quota.
    await store.update_metadata(session_id)
    await store.update_metadata(visitor_id)

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
) -> tuple[list[dict[str, Any]], bool, list[dict[str, Any]]]:
    """Build the system blocks (prompt, then resume context) for one turn.

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
    context = f"[{context_label}]\n{resume_context}"
    return system_blocks(system_prompt, context, context_is_static=not used_rag), used_rag, sources


async def prepare_generation(
    message: str,
    rag_pipeline: RAGPipeline | None,
    client: AsyncAnthropic,
    settings: Settings,
) -> tuple[list[dict[str, Any]], bool, list[dict[str, Any]], str, str]:
    """Run context retrieval and model routing concurrently (routing must not
    add serial time-to-first-token)."""
    (system, used_rag, sources), (model_id, route_reason) = await asyncio.gather(
        asyncio.to_thread(build_chat_context, message, rag_pipeline, settings),
        route_model(message, client, settings),
    )
    return system, used_rag, sources, model_id, route_reason


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
    usage: dict[str, int] | None = None,
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

    cost_usd = estimate_cost_usd(model_id, usage) if usage and model_id else None
    if usage:
        logger.info(
            "Model usage: model=%s route=%s input=%d cache_read=%d cache_write=%d "
            "output=%d est_cost_usd=%s",
            model_id, route_reason, usage["input_tokens"],
            usage["cache_read_input_tokens"], usage["cache_creation_input_tokens"],
            usage["output_tokens"], cost_usd,
        )

    # Log query for analytics (gitignored files; hashed id, never the live
    # bearer session id)
    await asyncio.to_thread(
        log_query,
        anonymize_session_id(session_id, settings.session_hash_secret),
        message,
        reply_text,
        model_id,
        route_reason,
        usage=usage,
        cost_usd=cost_usd,
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



@dataclass(frozen=True)
class JsonChatResult:
    reply: str
    session_id: str
    visitor_id: str
    sources: list[dict[str, Any]]
    used_rag: bool


async def run_json_chat_turn(
    payload: ChatRequest,
    request: Request,
    store: SessionStore,
    settings: Settings,
    pipeline: RAGPipeline | None,
    *,
    visitor_id: str | None = None,
) -> JsonChatResult:
    """One complete non-streaming chat turn: guardrails, starter cache,
    retrieval plus routing, generation with the primary-model fallback,
    refunds on failure, persistence.

    Shared by POST /api/chat and the MCP ``ask`` tool, so quota accounting is
    identical by construction. Raises HTTPException with the same statuses
    and visitor-facing messages as the route."""
    ctx = await run_chat_guardrails(payload, request, store, settings, visitor_id=visitor_id)
    session_id, message = ctx.session_id, ctx.message
    today = date.today().isoformat()

    async def _refund_on_error() -> None:
        # The visitor got an error, not an answer: return the reserved daily
        # budget unit AND the chat-quota unit consumed in the guardrails, so
        # an upstream 5xx never burns one of their few free exchanges.
        await store.release_daily_conversation(today)
        await store.release_chat_limit(ctx.visitor_id)

    # Starter question cache: instant responses for suggestion chips.
    # Only used when it's the first message in a session (no history yet).
    cache_key = starter_cache_key(message)
    history = await store.get_history(session_id)
    cached_reply = get_cached_starter(cache_key) if not history else None
    if cached_reply is not None:
        # Cache hit makes no model call, so return the daily unit reserved in
        # the guardrails: a free response must not consume the model budget.
        await store.release_daily_conversation(today)
        await persist_cached_reply(store, settings, session_id, message, cached_reply)
        return JsonChatResult(
            reply=cached_reply, session_id=session_id, visitor_id=ctx.visitor_id,
            sources=[], used_rag=False,
        )

    client = make_anthropic_client(settings)
    try:
        system, used_rag, sources, model_id, route_reason = (
            await prepare_generation(message, pipeline, client, settings)
        )
    except RuntimeError as exc:
        logger.exception("Failed to load prompt or resume data")
        await _refund_on_error()
        raise HTTPException(status_code=500, detail=GENERIC_CHAT_ERROR) from exc

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
                    **sampling_kwargs(attempt_model, 0.1),
                    system=system,
                    messages=build_api_messages(history, message),
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
        await _refund_on_error()
        raise HTTPException(status_code=503, detail=BUSY_MESSAGE) from exc
    except AnthropicError as exc:
        logger.exception("Anthropic API request failed after retries")
        await _refund_on_error()
        raise HTTPException(status_code=502, detail=GENERIC_CHAT_ERROR) from exc
    except Exception as exc:  # pragma: no cover - unexpected errors
        logger.exception("Unexpected error during chat request")
        await _refund_on_error()
        raise HTTPException(status_code=500, detail=UNEXPECTED_ERROR_MESSAGE) from exc

    had_text = bool(reply_text)
    if not reply_text:
        reply_text = EMPTY_REPLY_FALLBACK
    reply_text, _ = split_followups(reply_text)

    await persist_chat(
        store, settings, session_id, message, reply_text,
        history_was_empty=not history, cache_key=cache_key,
        model_id=model_id, route_reason=route_reason,
        cacheable=had_text, usage=usage_record(api_response),
    )
    return JsonChatResult(
        reply=reply_text, session_id=session_id, visitor_id=ctx.visitor_id,
        sources=sources, used_rag=used_rag,
    )

"""Chat endpoints: JSON (/api/chat) and SSE streaming (/api/chat/stream)."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import AsyncIterator

from anthropic import AnthropicError, RateLimitError
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from app import chat_service
from app.chat_service import (
    persist_cached_reply,
    persist_chat,
    prepare_generation,
    run_chat_guardrails,
    split_followups,
    sse,
    starter_cache_key,
)
from app.constants import BUSY_MESSAGE, GENERIC_CHAT_ERROR
from app.dependencies import app_settings, rag_pipeline
from app.identity import set_visitor_cookie
from app.llm import build_api_messages, make_anthropic_client, model_short_label, sampling_kwargs
from app.schemas import ChatRequest, ChatResponse
from app.session_store import get_session_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

EMPTY_REPLY_FALLBACK = (
    "I couldn't generate a response just now. "
    "Please try asking in a different way."
)


@router.post("/chat")
async def chat(payload: ChatRequest, request: Request, response: Response) -> ChatResponse:
    settings = app_settings(request)
    store = get_session_store()
    ctx = await run_chat_guardrails(payload, request, store, settings)
    session_id, message = ctx.session_id, ctx.message
    today = date.today().isoformat()
    set_visitor_cookie(response, ctx.visitor_id, settings)

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
    cached_reply = chat_service.get_cached_starter(cache_key) if not history else None
    if cached_reply is not None:
        # Cache hit makes no model call, so return the daily unit reserved in
        # the guardrails — a free response must not consume the model budget.
        await store.release_daily_conversation(today)
        await persist_cached_reply(store, settings, session_id, message, cached_reply)
        return ChatResponse(reply=cached_reply, session_id=session_id)

    client = make_anthropic_client(settings)
    try:
        system_message, used_rag, sources, model_id, route_reason = (
            await prepare_generation(message, rag_pipeline(request), client, settings)
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
                    system=system_message,
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
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again.",
        ) from exc

    had_text = bool(reply_text)
    if not reply_text:
        reply_text = EMPTY_REPLY_FALLBACK
    reply_text, _ = split_followups(reply_text)

    await persist_chat(
        store, settings, session_id, message, reply_text,
        history_was_empty=not history, cache_key=cache_key,
        model_id=model_id, route_reason=route_reason,
        cacheable=had_text,
    )

    return ChatResponse(
        reply=reply_text, session_id=session_id,
        sources=[s["title"] for s in sources], used_rag=used_rag,
    )


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    """SSE chat: real pipeline events (retrieval, routing) then token deltas.

    All guardrails raise plain HTTPExceptions BEFORE the stream starts, so
    the frontend's 403-unlock and error handling work exactly as for
    /api/chat. Only failures after headers are sent become `error` events.
    """
    settings = app_settings(request)
    store = get_session_store()
    ctx = await run_chat_guardrails(payload, request, store, settings)
    session_id, message = ctx.session_id, ctx.message
    today = date.today().isoformat()

    cache_key = starter_cache_key(message)
    history = await store.get_history(session_id)
    cached_reply = chat_service.get_cached_starter(cache_key) if not history else None
    quota_remaining = await store.get_remaining_quota(
        ctx.visitor_id, settings.free_chat_limit
    )
    pipeline = rag_pipeline(request)

    async def _refund_on_error() -> None:
        # Streamed an error, not an answer: return the reserved daily budget
        # unit AND the chat-quota unit consumed in the guardrails. (Client
        # disconnects keep the turn — they may have received partial content.)
        await store.release_daily_conversation(today)
        await store.release_chat_limit(ctx.visitor_id)

    async def event_gen() -> AsyncIterator[str]:
        yield sse("session", {"session_id": session_id})

        if cached_reply is not None:
            # Cache hit makes no model call, so return the daily unit
            # reserved in the guardrails — a free response must not consume
            # the model budget.
            await store.release_daily_conversation(today)
            yield sse("status", {"stage": "cached", "state": "done"})
            yield sse("delta", {"text": cached_reply})
            await persist_cached_reply(store, settings, session_id, message, cached_reply)
            yield sse("done", {
                "reply": cached_reply, "used_rag": False, "sources": [],
                "session_id": session_id, "model": "", "followups": [],
                "quota_remaining": quota_remaining,
            })
            return

        yield sse("status", {"stage": "rag_search", "state": "start"})
        client = make_anthropic_client(settings)
        try:
            system_message, used_rag, sources, model_id, route_reason = (
                await prepare_generation(message, pipeline, client, settings)
            )
        except RuntimeError:
            logger.exception("Failed to load prompt or resume data")
            await _refund_on_error()
            yield sse("error", {"detail": GENERIC_CHAT_ERROR})
            return
        yield sse("status", {
            "stage": "rag_search", "state": "done",
            "used_rag": used_rag, "sources": sources,
        })
        yield sse("status", {
            "stage": "routing", "state": "done",
            "model": model_short_label(model_id), "reason": route_reason,
        })
        yield sse("status", {"stage": "generation", "state": "start"})

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
                        **sampling_kwargs(attempt_model, 0.1),
                        system=system_message,
                        messages=build_api_messages(history, message),
                    ) as stream:
                        async for text in stream.text_stream:
                            streamed_any = True
                            yield sse("delta", {"text": text})
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
            had_text = bool(reply_text)
            if not reply_text:
                reply_text = EMPTY_REPLY_FALLBACK
            reply_text, followups = split_followups(reply_text)

            await persist_chat(
                store, settings, session_id, message, reply_text,
                history_was_empty=not history, cache_key=cache_key,
                model_id=used_model, route_reason=route_reason,
                cacheable=had_text,
            )
            yield sse("done", {
                "reply": reply_text, "used_rag": used_rag, "sources": sources,
                "session_id": session_id, "model": model_short_label(used_model),
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
            await _refund_on_error()
            yield sse("error", {"detail": BUSY_MESSAGE})
        except AnthropicError:
            logger.exception("Anthropic API request failed after retries")
            await _refund_on_error()
            yield sse("error", {"detail": GENERIC_CHAT_ERROR})
        except Exception:  # pragma: no cover - unexpected errors
            logger.exception("Unexpected error during streamed chat")
            await _refund_on_error()
            yield sse("error", {"detail": "An unexpected error occurred. Please try again."})

    streaming_response = StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
    set_visitor_cookie(streaming_response, ctx.visitor_id, settings)
    return streaming_response

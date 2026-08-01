"""Job-description fit analysis (SSE) with its own daily budget."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from typing import AsyncIterator

from anthropic import AnthropicError, RateLimitError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.chat_service import (
    persist_chat,
    run_chat_guardrails,
    split_followups,
    sse,
)
from app.constants import BUSY_MESSAGE, GENERIC_CHAT_ERROR, JD_LIMIT_MESSAGE, JD_SENTINEL
from app.content import load_jd_match_prompt, load_resume_context, load_system_prompt
from app.dependencies import app_settings
from app.identity import get_client_ip, set_visitor_cookie
from app.llm import build_api_messages, make_anthropic_client, sampling_kwargs
from app.schemas import ChatRequest, JDMatchRequest
from app.session_store import get_session_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Strip BOTH tag forms (opening and closing) case-insensitively so pasted
# text can't forge or break the prompt delimiter.
_JD_TAG_RE = re.compile(r"</?\s*job_description", re.IGNORECASE)


def sanitize_jd_text(jd_text: str) -> str:
    return _JD_TAG_RE.sub("", jd_text)


@router.post("/jd-match")
async def jd_match(payload: JDMatchRequest, request: Request) -> StreamingResponse:
    """SSE job-fit analysis for a pasted job description.

    Draws from its own daily budget (jd_daily_limit) so it never consumes
    the chat quota; password unlock bypasses it. The pasted JD is untrusted:
    delimiter tags are stripped and it rides in the user turn only. Briefs
    are quota-free but require a prior analysis in this session.
    """
    settings = app_settings(request)
    store = get_session_store()
    guard_payload = ChatRequest(message=payload.jd_text, session_id=payload.session_id)
    ctx = await run_chat_guardrails(
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
    jd_rate_key = f"jd:{get_client_ip(request, settings)}"
    if not await store.check_rate_limit(jd_rate_key, max_requests=3, window=600.0):
        await _reject(HTTPException(
            status_code=429,
            detail="Too many fit analyses at once. Please wait a few minutes and try again.",
        ))

    history = await store.get_history(session_id)

    if payload.mode == "brief":
        # Server-owned flag, not a history substring: a visitor must not be
        # able to unlock the quota-free brief by typing a sentinel into an
        # ordinary chat message that shares this session's history.
        if not await store.has_jd_analysis(session_id):
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

    sanitized = sanitize_jd_text(ctx.message)
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
        # Persist only a neutral marker, never the raw pasted JD: without its
        # <job_description> firewall wrapper the JD would otherwise replay as
        # a plain user turn on later chat turns, stripped of the "untrusted
        # data, not instructions" framing that is the JD defense.
        stored_user_text = JD_SENTINEL

    async def event_gen() -> AsyncIterator[str]:
        yield sse("session", {"session_id": session_id})
        yield sse("status", {"stage": "context_load", "state": "start"})
        try:
            system_message = (
                f"{load_system_prompt()}\n\n{load_jd_match_prompt()}"
                f"\n\n[RESUME DATA]\n{load_resume_context()}"
            )
        except RuntimeError:
            logger.exception("Failed to load prompt or resume data")
            await _release_budgets()
            yield sse("error", {"detail": GENERIC_CHAT_ERROR})
            return
        yield sse("status", {"stage": "context_load", "state": "done"})
        yield sse("status", {"stage": "generation", "state": "start"})

        # Always the primary model: JD analysis is the synthesis-heavy case.
        client = make_anthropic_client(settings)
        try:
            async with client.messages.stream(
                model=settings.anthropic_model,
                max_tokens=settings.anthropic_max_tokens,
                **sampling_kwargs(settings.anthropic_model, 0.1),
                system=system_message,
                messages=build_api_messages(history, user_text),
            ) as stream:
                async for text in stream.text_stream:
                    yield sse("delta", {"text": text})
                final = await stream.get_final_message()

            reply_text = "".join(
                block.text for block in final.content if block.type == "text"
            )
            if not reply_text:
                reply_text = (
                    "I couldn't generate the analysis just now. "
                    "Please try again."
                )
            reply_text, _ = split_followups(reply_text)

            await persist_chat(
                store, settings, session_id, stored_user_text, reply_text,
                history_was_empty=False, cache_key="",
                model_id=settings.anthropic_model, route_reason="jd-match",
            )
            if payload.mode != "brief":
                # Unlock brief mode for this session via a server-owned flag.
                await store.mark_jd_analysis(session_id)
            yield sse("done", {
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
            yield sse("error", {"detail": BUSY_MESSAGE})
        except AnthropicError:
            logger.exception("Anthropic API request failed after retries")
            await _release_budgets()
            yield sse("error", {"detail": GENERIC_CHAT_ERROR})
        except Exception:  # pragma: no cover - unexpected errors
            logger.exception("Unexpected error during JD analysis")
            await _release_budgets()
            yield sse("error", {"detail": "An unexpected error occurred. Please try again."})

    streaming_response = StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
    set_visitor_cookie(streaming_response, ctx.visitor_id, settings)
    return streaming_response

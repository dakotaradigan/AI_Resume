"""Job-description fit analysis (SSE) with its own daily budget."""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from anthropic import AnthropicError, RateLimitError
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.chat_service import UNEXPECTED_ERROR_MESSAGE, sse
from app.constants import BUSY_MESSAGE, GENERIC_CHAT_ERROR
from app.dependencies import app_settings
from app.identity import set_visitor_cookie
from app.jd_service import (
    FIT_MAP_GRACE_SECONDS,
    build_jd_prompt,
    finish_jd_turn,
    prepare_jd_turn,
    start_fit_map,
)
from app.llm import build_api_messages, make_anthropic_client, sampling_kwargs, usage_record
from app.schemas import JDMatchRequest
from app.session_store import get_session_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.post("/jd-match")
async def jd_match(payload: JDMatchRequest, request: Request) -> StreamingResponse:
    """SSE job-fit analysis for a pasted job description.

    The guardrails, budgets, prompt and persistence live in jd_service, shared
    with the MCP ``analyze_fit`` tool; this route adds the stream. When Jev is
    configured, an analysis also carries a requirement map (``fitmap`` event):
    Jev's per-requirement evidence levels, judged in parallel with the prose
    and sent as soon as they are ready, before ``done``. The map is optional;
    its failure never touches the analysis.
    """
    settings = app_settings(request)
    turn = await prepare_jd_turn(payload, request, get_session_store(), settings)

    async def event_gen() -> AsyncIterator[str]:
        yield sse("session", {"session_id": turn.session_id})
        yield sse("status", {"stage": "context_load", "state": "start"})
        try:
            prompt = build_jd_prompt(turn.mode, turn.sanitized)
        except RuntimeError:
            logger.exception("Failed to load prompt or resume data")
            await turn.release_budgets()
            yield sse("error", {"detail": GENERIC_CHAT_ERROR})
            return
        yield sse("status", {"stage": "context_load", "state": "done"})
        yield sse("status", {"stage": "generation", "state": "start"})

        fit_task = start_fit_map(turn, prompt, settings)

        def _take_fit_map() -> dict | None:
            nonlocal fit_task
            if fit_task is None or not fit_task.done():
                return None
            fit_map, fit_task = fit_task.result(), None
            return fit_map

        # Always the primary model: JD analysis is the synthesis-heavy case.
        client = make_anthropic_client(settings)
        try:
            async with client.messages.stream(
                model=settings.anthropic_model,
                max_tokens=settings.anthropic_max_tokens,
                **sampling_kwargs(settings.anthropic_model, 0.1),
                system=prompt.system,
                messages=build_api_messages(turn.history, prompt.user_text),
            ) as stream:
                async for text in stream.text_stream:
                    yield sse("delta", {"text": text})
                    fit_map = _take_fit_map()
                    if fit_map:
                        yield sse("fitmap", fit_map)
                final = await stream.get_final_message()

            if fit_task is not None:
                # Jev is normally long done by now. Give it a short grace so
                # the finished analysis is never held hostage to a slow map.
                await asyncio.wait({fit_task}, timeout=FIT_MAP_GRACE_SECONDS)
                fit_map = _take_fit_map()
                if fit_map:
                    yield sse("fitmap", fit_map)

            reply_text = "".join(
                block.text for block in final.content if block.type == "text"
            )
            reply_text = await finish_jd_turn(
                settings, turn, prompt.stored_user_text, reply_text, usage_record(final)
            )
            yield sse("done", {
                "reply": reply_text, "mode": turn.mode,
                "session_id": turn.session_id, "used_rag": False, "sources": [],
                "followups": [], "quota_remaining": None,
            })
        except asyncio.CancelledError:
            logger.info("Client disconnected mid-analysis; skipping persistence")
            await turn.release_budgets()
            raise
        except RateLimitError:
            logger.warning("Anthropic rate limit or spending cap hit")
            await turn.release_budgets()
            yield sse("error", {"detail": BUSY_MESSAGE})
        except AnthropicError:
            logger.exception("Anthropic API request failed after retries")
            await turn.release_budgets()
            yield sse("error", {"detail": GENERIC_CHAT_ERROR})
        except Exception:  # pragma: no cover - unexpected errors
            logger.exception("Unexpected error during JD analysis")
            await turn.release_budgets()
            yield sse("error", {"detail": UNEXPECTED_ERROR_MESSAGE})
        finally:
            # A map with no analysis to sit beside is never sent.
            if fit_task is not None and not fit_task.done():
                fit_task.cancel()

    streaming_response = StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
    set_visitor_cookie(streaming_response, turn.visitor_id, settings)
    return streaming_response

"""Job-description fit analysis: the turn shared by /api/jd-match and MCP.

The pasted JD is untrusted: delimiter tags are stripped and it rides in the
user turn only, inside a <job_description> block, and only a neutral marker
is ever persisted. Analyses draw from their own daily budget
(jd_daily_limit) so they never consume the chat quota; password unlock
bypasses it. Briefs are quota-free but need a prior analysis in the session.

``prepare_jd_turn`` runs every guardrail and reserves the budgets,
``build_jd_prompt`` assembles the prompt, ``finish_jd_turn`` persists and
unlocks brief mode. The streaming route composes them around its SSE
stream; ``run_json_jd_turn`` composes them around one non-streaming call
for the MCP ``analyze_fit`` tool, so both entry points account identically.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from anthropic import AnthropicError, RateLimitError
from fastapi import HTTPException, Request

from app.chat_service import (
    UNEXPECTED_ERROR_MESSAGE,
    persist_chat,
    run_chat_guardrails,
    split_followups,
)
from app.config import Settings
from app.constants import BUSY_MESSAGE, GENERIC_CHAT_ERROR, JD_LIMIT_MESSAGE, JD_SENTINEL
from app.content import load_jd_match_prompt, load_resume_context, load_system_prompt
from app.fit_map import build_fit_map
from app.identity import get_client_ip
from app.llm import (
    build_api_messages,
    make_anthropic_client,
    sampling_kwargs,
    system_blocks,
    usage_record,
)
from app.schemas import ChatRequest, JDMatchRequest
from app.session_store import SessionStore

logger = logging.getLogger(__name__)

# Strip BOTH tag forms (opening and closing) case-insensitively so pasted
# text can't forge or break the prompt delimiter.
_JD_TAG_RE = re.compile(r"</?\s*job_description", re.IGNORECASE)

# How long a finished analysis waits for a straggling requirement map.
FIT_MAP_GRACE_SECONDS = 3.0

EMPTY_ANALYSIS_FALLBACK = "I couldn't generate the analysis just now. Please try again."


def sanitize_jd_text(jd_text: str) -> str:
    return _JD_TAG_RE.sub("", jd_text)


@dataclass
class JDTurn:
    """A fit-analysis turn past its guardrails: identity, the sanitized
    posting, prior history, and the budget units to return on failure."""

    store: SessionStore
    session_id: str
    visitor_id: str
    mode: str
    sanitized: str
    history: list[dict]
    today: str
    jd_unit_reserved: bool

    async def release_budgets(self) -> None:
        # A failed or cancelled generation must return BOTH budget units: the
        # global daily reservation and, when one was taken, the visitor's JD
        # unit. Nobody loses their free analysis to a 529.
        await self.store.release_daily_conversation(self.today)
        if self.jd_unit_reserved:
            await self.store.release_scoped_limit(self.visitor_id, "jd", self.today)


@dataclass(frozen=True)
class JDPrompt:
    system: list[dict[str, Any]]
    user_text: str
    stored_user_text: str
    resume_context: str


async def prepare_jd_turn(
    payload: JDMatchRequest,
    request: Request,
    store: SessionStore,
    settings: Settings,
    *,
    visitor_id: str | None = None,
) -> JDTurn:
    """Guardrails, the JD rate limit, brief-mode gating and the budget
    reservations. Raises HTTPException with visitor-facing detail."""
    guard_payload = ChatRequest(message=payload.jd_text, session_id=payload.session_id)
    ctx = await run_chat_guardrails(
        guard_payload, request, store, settings,
        max_chars=settings.max_jd_chars, consume_quota=False, visitor_id=visitor_id,
    )
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

    history = await store.get_history(ctx.session_id)

    if payload.mode == "brief":
        # Server-owned flag, not a history substring: a visitor must not be
        # able to unlock the quota-free brief by typing a sentinel into an
        # ordinary chat message that shares this session's history.
        if not await store.has_jd_analysis(ctx.session_id):
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

    return JDTurn(
        store=store, session_id=ctx.session_id, visitor_id=ctx.visitor_id,
        mode=payload.mode, sanitized=sanitize_jd_text(ctx.message),
        history=history, today=today, jd_unit_reserved=jd_unit_reserved,
    )


def build_jd_prompt(mode: str, sanitized: str) -> JDPrompt:
    """The system blocks and user turn for an analysis or a brief. Raises
    RuntimeError when the prompt or resume files cannot be read."""
    resume_context = load_resume_context()
    # The first block is byte-identical to the chat path's, so a JD
    # analysis and a chat turn share one cache entry for the prompt.
    system = system_blocks(
        load_system_prompt(),
        f"{load_jd_match_prompt()}\n\n[RESUME DATA]\n{resume_context}",
        context_is_static=True,
    )
    if mode == "brief":
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
    return JDPrompt(
        system=system, user_text=user_text,
        stored_user_text=stored_user_text, resume_context=resume_context,
    )


def start_fit_map(turn: JDTurn, prompt: JDPrompt, settings: Settings) -> asyncio.Task | None:
    """The requirement map runs beside the prose, never in series with it:
    Jev judges every candidate line in one request while Claude writes."""
    if turn.mode == "brief" or not settings.typesafe_api_key:
        return None
    return asyncio.create_task(build_fit_map(turn.sanitized, prompt.resume_context, settings))


async def settle_fit_map(fit_task: asyncio.Task | None) -> dict | None:
    """The map if it is ready within the grace period, else None; a map with
    no analysis to sit beside is never sent, so a late task is cancelled."""
    if fit_task is None:
        return None
    await asyncio.wait({fit_task}, timeout=FIT_MAP_GRACE_SECONDS)
    if not fit_task.done():
        fit_task.cancel()
        return None
    return fit_task.result() or None


async def finish_jd_turn(
    settings: Settings,
    turn: JDTurn,
    stored_user_text: str,
    reply_text: str,
    usage: dict[str, int] | None,
) -> str:
    """Persist the turn and unlock brief mode. Returns the cleaned reply."""
    if not reply_text:
        reply_text = EMPTY_ANALYSIS_FALLBACK
    reply_text, _ = split_followups(reply_text)
    await persist_chat(
        turn.store, settings, turn.session_id, stored_user_text, reply_text,
        history_was_empty=False, cache_key="",
        model_id=settings.anthropic_model, route_reason="jd-match", usage=usage,
    )
    if turn.mode != "brief":
        # Unlock brief mode for this session via a server-owned flag.
        await turn.store.mark_jd_analysis(turn.session_id)
    return reply_text


async def run_json_jd_turn(
    payload: JDMatchRequest,
    request: Request,
    store: SessionStore,
    settings: Settings,
    *,
    visitor_id: str | None = None,
) -> tuple[str, str, dict | None]:
    """One complete non-streaming fit analysis for the MCP tool. Returns
    (analysis, session_id, requirement map or None)."""
    turn = await prepare_jd_turn(payload, request, store, settings, visitor_id=visitor_id)
    try:
        prompt = build_jd_prompt(turn.mode, turn.sanitized)
    except RuntimeError as exc:
        logger.exception("Failed to load prompt or resume data")
        await turn.release_budgets()
        raise HTTPException(status_code=500, detail=GENERIC_CHAT_ERROR) from exc

    fit_task = start_fit_map(turn, prompt, settings)
    # Always the primary model: JD analysis is the synthesis-heavy case.
    client = make_anthropic_client(settings)
    api_response = None
    try:
        api_response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            **sampling_kwargs(settings.anthropic_model, 0.1),
            system=prompt.system,
            messages=build_api_messages(turn.history, prompt.user_text),
        )
    except asyncio.CancelledError:
        await turn.release_budgets()
        raise
    except RateLimitError as exc:
        logger.warning("Anthropic rate limit or spending cap hit")
        await turn.release_budgets()
        raise HTTPException(status_code=503, detail=BUSY_MESSAGE) from exc
    except AnthropicError as exc:
        logger.exception("Anthropic API request failed after retries")
        await turn.release_budgets()
        raise HTTPException(status_code=502, detail=GENERIC_CHAT_ERROR) from exc
    except Exception as exc:  # pragma: no cover - unexpected errors
        logger.exception("Unexpected error during JD analysis")
        await turn.release_budgets()
        raise HTTPException(status_code=500, detail=UNEXPECTED_ERROR_MESSAGE) from exc
    finally:
        # A map with no analysis to sit beside is never sent.
        if fit_task is not None and api_response is None:
            fit_task.cancel()

    fit_map = await settle_fit_map(fit_task)
    reply_text = "".join(
        block.text for block in api_response.content if block.type == "text"
    )
    reply_text = await finish_jd_turn(
        settings, turn, prompt.stored_user_text, reply_text, usage_record(api_response)
    )
    return reply_text, turn.session_id, fit_map

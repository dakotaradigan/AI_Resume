"""Feature-use events: anonymous counts of what visitors do on the page."""

from __future__ import annotations

import asyncio

from analytics.analytics import anonymize_session_id, log_event
from fastapi import APIRouter, Request, Response

from app.dependencies import app_settings
from app.identity import get_client_ip
from app.schemas import EventRequest
from app.session_store import get_session_store

router = APIRouter(prefix="/api")


@router.post("/event", status_code=204)
async def record_event(payload: EventRequest, request: Request) -> Response:
    """Count one feature use (see analytics.USAGE_EVENTS).

    The page sends these without waiting and ignores the answer, so this
    never reports a problem to the visitor: past the rate limit an event is
    dropped, not refused. The limit keeps one client from filling the log
    or inflating the counts.
    """
    settings = app_settings(request)
    rate_limit_key = f"event:{get_client_ip(request, settings)}"
    allowed = await get_session_store().check_rate_limit(
        rate_limit_key, max_requests=30, window=60.0
    )
    if allowed:
        await asyncio.to_thread(
            log_event,
            anonymize_session_id(payload.session_id or "", settings.session_hash_secret),
            payload.event,
        )
    return Response(status_code=204)

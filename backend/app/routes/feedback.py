"""User feedback logging (thumbs up/down)."""

from __future__ import annotations

import asyncio

from analytics.analytics import anonymize_session_id, log_feedback
from fastapi import APIRouter, HTTPException, Request

from app.dependencies import app_settings
from app.identity import get_client_ip
from app.schemas import FeedbackRequest
from app.session_store import get_session_store

router = APIRouter(prefix="/api")


@router.post("/feedback")
async def submit_feedback(payload: FeedbackRequest, request: Request):
    """Log user feedback (thumbs up/down)."""
    settings = app_settings(request)
    store = get_session_store()

    # Rate limit: prevent unbounded writes to the feedback log
    rate_limit_key = f"feedback:{get_client_ip(request, settings)}"
    allowed = await store.check_rate_limit(rate_limit_key, max_requests=10, window=60.0)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too much feedback at once. Please wait a moment and try again.",
        )

    await asyncio.to_thread(
        log_feedback,
        anonymize_session_id(payload.session_id, settings.session_hash_secret),
        payload.rating,
        payload.comment,
        payload.trigger
    )
    return {"success": True}

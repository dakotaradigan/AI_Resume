"""Password unlock: grants unlimited access to the visitor identity."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Request, Response

from app.dependencies import app_settings
from app.identity import get_client_ip, resolve_visitor_id, set_visitor_cookie
from app.schemas import UnlockRequest, UnlockResponse
from app.session_store import get_session_store

router = APIRouter(prefix="/api")


@router.post("/unlock")
async def unlock_chat(
    payload: UnlockRequest, request: Request, response: Response
) -> UnlockResponse:
    """
    Unlock unlimited chat access with password.
    Password is found on Dakota's resume PDF.

    Unlock is granted to the server-minted visitor identity, so it
    survives cleared localStorage and new session ids. This may be the
    visitor's first request — the cookie is minted and set here too.
    """
    settings = app_settings(request)
    store = get_session_store()
    visitor_id, _ = resolve_visitor_id(request, settings)
    set_visitor_cookie(response, visitor_id, settings)

    # Rate limit brute-force attempts per IP AND per visitor identity
    # (5 per minute each).
    ip_allowed = await store.check_rate_limit(
        f"unlock:{get_client_ip(request, settings)}", max_requests=5, window=60.0
    )
    visitor_allowed = await store.check_rate_limit(
        f"unlock:visitor:{visitor_id}", max_requests=5, window=60.0
    )
    if not (ip_allowed and visitor_allowed):
        return UnlockResponse(
            success=False,
            message="Too many attempts. Please wait a moment and try again."
        )

    # Check if password is configured
    if not settings.chat_password:
        return UnlockResponse(
            success=False,
            message="Chat password not configured."
        )

    # Verify password (case-insensitive, constant-time comparison)
    provided = payload.password.strip().lower()
    if not provided or not hmac.compare_digest(provided, settings.chat_password.lower()):
        return UnlockResponse(
            success=False,
            message="Incorrect password. Please check Dakota's resume."
        )

    # Grant unlimited access to the visitor identity
    await store.update_metadata(visitor_id)
    await store.set_unlimited(visitor_id, True)

    return UnlockResponse(
        success=True,
        message="Unlimited chat access granted! Continue the conversation."
    )

"""Admin authentication for operator endpoints."""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request

from app.config import Settings
from app.identity import is_loopback_host


def require_admin(request: Request, x_admin_token: str | None, settings: Settings) -> None:
    """Authorize an admin request or raise.

    With ADMIN_TOKEN configured, requires a matching X-Admin-Token header
    (constant-time compare). Without it, only loopback requests in local
    development are allowed; everywhere else the endpoint fails closed.
    """
    if settings.admin_token:
        # Compared as bytes: compare_digest raises TypeError for a str with
        # non-ASCII characters, which turned a wrong token into a 500.
        if not hmac.compare_digest(
            (x_admin_token or "").encode("utf-8"), settings.admin_token.encode("utf-8")
        ):
            raise HTTPException(status_code=401, detail="Unauthorized.")
        return
    client_host = request.client.host if request.client else ""
    if settings.environment != "development" or not is_loopback_host(client_host):
        raise HTTPException(
            status_code=503,
            detail="Admin endpoint disabled (ADMIN_TOKEN not configured).",
        )

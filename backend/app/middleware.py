"""CORS and security-header middleware."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings

PRODUCTION_ORIGINS = [
    "https://chat.dakotaradigan.io",
    "https://www.dakotaradigan.io",
    "https://dakotaradigan.io",
    "https://dakotaradigan.ai",
    "https://www.dakotaradigan.ai",
]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Clickjacking, MIME-sniffing, and XSS protections on every response."""

    def __init__(self, app, production: bool = False):
        super().__init__(app)
        self._production = production

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # Force revalidation (cheap 304s via StaticFiles ETags) so shipped
        # frontend changes take effect immediately — HTML depends on fresh
        # app.js to enable controls, and stale caches froze the JD button.
        if "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # HSTS only in production: forcing HTTPS-only would break local http
        # dev. Confirm the edge isn't already sending this before relying on it.
        if self._production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains"
            )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'"
        )
        return response


def install_middleware(app: FastAPI, settings: Settings) -> None:
    """Add CORS and security headers, environment-aware."""
    if settings.environment == "production":
        allowed_origins = PRODUCTION_ORIGINS
        allow_credentials = True
    else:
        # Development: support local servers + direct file open flows.
        # Note: credentials + wildcard origin is invalid per the CORS spec.
        allowed_origins = ["*"]
        allow_credentials = False

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        SecurityHeadersMiddleware,
        production=settings.environment == "production",
    )

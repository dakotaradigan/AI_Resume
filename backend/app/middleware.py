"""CORS, security-header and request-size middleware."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import Settings

# Every origin here may make credentialed requests, so list a hostname only
# while it serves this app. chat.dakotaradigan.io was removed for that reason:
# its DNS record outlived the service behind it, and whoever came to hold the
# name would have inherited that trust.
PRODUCTION_ORIGINS = [
    "https://www.dakotaradigan.io",
    "https://dakotaradigan.io",
    "https://dakotaradigan.ai",
    "https://www.dakotaradigan.ai",
]

# One constant, pinned by tests/test_security_headers.py. default-src does
# not cover the last four directives: without object-src a script injection
# could embed a plugin; without frame-ancestors a parent page could frame
# the site (X-Frame-Options covers older browsers only); without base-uri an
# injected <base> tag could redirect every relative URL; without form-action
# a form could post what it collects to another origin.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    # Fonts are self-hosted (frontend/fonts), so styles and fonts never
    # leave this origin.
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


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
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        return response


BODY_TOO_LARGE_MESSAGE = "Request body too large."


def max_request_body_bytes(settings: Settings) -> int:
    """The largest body any endpoint needs: a fit analysis at max_jd_chars.

    Sized from the settings, so raising a text limit can never be clipped
    by a forgotten constant here. JSON may spend 12 bytes on one character
    (an escaped surrogate pair); the allowance on top covers the envelope
    and the other fields.
    """
    longest_text = max(settings.max_jd_chars, settings.max_user_message_chars)
    return longest_text * 12 + 16 * 1024


class BodySizeLimitMiddleware:
    """Refuse a request body above ``max_bytes`` before it is buffered.

    The framework reads a whole JSON body into memory before any route code
    or guardrail runs, and the server sets no limit of its own: a 200 MB
    POST cost hundreds of megabytes before the message-length check could
    answer 413. A declared Content-Length above the cap is refused at once,
    unread. A body with no declared length (chunked) is counted as it
    arrives. Pure ASGI, so streamed responses pass through untouched.
    """

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Connection: close stops the server reading the rest of an upload
        # it has already refused.
        close = {"Connection": "close"}
        declared = Headers(scope=scope).get("content-length", "")
        if declared.isdigit() and int(declared) > self.max_bytes:
            refusal = JSONResponse(
                {"detail": BODY_TOO_LARGE_MESSAGE}, status_code=413, headers=close
            )
            await refusal(scope, receive, send)
            return

        received = 0

        async def counted_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Raised inside the route's body read, so the framework
                    # turns it into an ordinary 413 response.
                    raise HTTPException(
                        status_code=413, detail=BODY_TOO_LARGE_MESSAGE, headers=close
                    )
            return message

        await self.app(scope, counted_receive, send)


def install_middleware(app: FastAPI, settings: Settings) -> None:
    """Add the body cap, CORS and security headers, environment-aware."""
    # Added first, so it is innermost: its refusals pass back out through
    # CORS and the security headers like any other response. Nothing outside
    # it reads the body.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_request_body_bytes(settings))

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

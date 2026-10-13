"""Per-request context for logs: a request id on every response and on
every log line emitted while the request runs.

The id rides in a ContextVar rather than a function argument: asyncio
copies the context into every task a request spawns, so a line logged in
a route, a service, or a to_thread worker still carries it. It is echoed
as X-Request-ID so a person quoting an error can be matched to the exact
log lines.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar

REQUEST_ID_HEADER = "x-request-id"

# What we accept from an upstream proxy: one token, no whitespace or control
# characters, bounded, so a caller can never smuggle a newline or a megabyte
# into every log line of their request.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def accept_request_id(raw: str | None) -> str:
    """The caller's id when it is well-formed (an edge proxy stamps one per
    hop, and keeping it lets edge and app logs be joined), else a fresh one."""
    if raw and _REQUEST_ID_RE.match(raw):
        return raw
    return uuid.uuid4().hex


class RequestContextMiddleware:
    """Pure ASGI (streaming-safe) and outermost: binds the request id before
    any other middleware runs and stamps it on the response.

    The ContextVar is deliberately not reset on exit: the server runs each
    request in its own task, whose context dies with it, and resetting early
    would strip the id from the one line that matters most, the traceback
    the server logs after an unhandled exception unwinds past here."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for key, value in scope.get("headers", []):
            if key == REQUEST_ID_HEADER.encode("latin-1"):
                incoming = value.decode("latin-1")
                break
        request_id = accept_request_id(incoming)
        request_id_var.set(request_id)

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_id)


class RequestContextFilter(logging.Filter):
    """Stamps ``request_id`` onto every record passing through the handler
    it is attached to (empty outside a request)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True

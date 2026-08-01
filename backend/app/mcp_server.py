"""MCP endpoint: a data-only get_resume tool over streamable HTTP."""

from __future__ import annotations

from typing import Any

from fastapi.responses import RedirectResponse

from app.content import load_resume_json_public


def build_mcp_server():
    """MCP server with exactly ONE tool: get_resume (data-only).

    An LLM-invoking tool (ask_resume) was reviewed and rejected: it would be
    an unauthenticated LLM proxy able to starve the global daily budget. The
    connected client's own model does the reasoning over the raw resume.
    """
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    server = FastMCP(
        "dakota-resume",
        instructions=(
            "Dakota Radigan's resume. Call get_resume for the full structured "
            "resume JSON (experience, projects, skills, education, certifications)."
        ),
        stateless_http=True,
    )
    # The sub-app is mounted at /mcp by the parent app; serve at its root.
    server.settings.streamable_http_path = "/"
    # The SDK's DNS-rebinding protection rejects any Host not on its
    # allowlist (default: localhost only) with 421 — including the real
    # domain. This server is public, unauthenticated, and data-only, so
    # rebinding protection defends nothing; disable it rather than chase
    # the domain list.
    server.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )

    @server.tool()
    def get_resume() -> dict:
        """Dakota Radigan's full resume as structured JSON (phone number excluded)."""
        return load_resume_json_public()

    return server


class McpOrBrowser:
    """ASGI wrapper (a class instance so Starlette treats it as an ASGI
    app, not a GET-only request handler). A human opening /mcp in a
    browser would get a bare JSON-RPC "Not Acceptable" error; send them
    to the connect instructions instead. Real MCP clients GET with
    Accept: text/event-stream."""

    def __init__(self, endpoint: Any) -> None:
        self.endpoint = endpoint

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope.get("method") == "GET":
            accept = next(
                (v.decode() for k, v in scope.get("headers", []) if k == b"accept"), ""
            )
            if "text/event-stream" not in accept:
                redirect = RedirectResponse(
                    "/how-it-works.html#connect-mcp", status_code=302
                )
                await redirect(scope, receive, send)
                return
        await self.endpoint(scope, receive, send)

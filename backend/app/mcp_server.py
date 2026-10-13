"""MCP endpoint: get_resume (data-only), ask, and analyze_fit over streamable HTTP.

get_resume returns the public résumé JSON. ask and analyze_fit run the SAME
guarded pipelines as the web page (chat_service.run_json_chat_turn and
jd_service.run_json_jd_turn): the per-minute rate limit, the free chat
quota, the per-IP daily cap, the global daily budget with reserve-before-
call and release on failure, the JD daily unit, and per-turn token
metering. That is what makes an LLM tool safe to expose where a bare one
was rejected before: it would have been an unauthenticated proxy able to
drain the daily budget.

MCP clients hold no cookies, so the visitor identity is derived from the
client IP, keyed with the session secret so one caller cannot derive
another's id. Only when the client IP is real: proxy headers trusted
(Railway), or the box declared it has no proxy. Otherwise every caller
would share the proxy's address and one caller's free turns would lock
everyone out, so the binding fails open (a fresh identity per call, like a
cookie-less browser) and the rate limit and daily budget still bind.

Error posture: FastMCP sends str(exception) to the client, so every tool
runs behind _run_tool, which passes through guardrail refusals (their
detail strings are visitor-facing) and replaces everything else with the
generic strings the web routes use.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextvars import ContextVar
from typing import Any, Awaitable, Callable

from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from starlette.requests import Request

from app.chat_service import UNEXPECTED_ERROR_MESSAGE, run_json_chat_turn
from app.config import Settings
from app.content import load_resume_json_public
from app.dependencies import app_settings, rag_pipeline
from app.identity import get_client_ip
from app.jd_service import run_json_jd_turn
from app.schemas import ChatRequest, JDMatchRequest
from app.session_store import get_session_store

logger = logging.getLogger(__name__)

# The ASGI scope of the request a tool is answering, set by McpOrBrowser
# before it delegates to the MCP endpoint. ContextVars are task-local and
# propagate into the tasks the session manager spawns for the call.
_current_scope: ContextVar[dict | None] = ContextVar("mcp_current_scope", default=None)


class _SafeToolError(ValueError):
    """A tool error whose message is visitor-facing by construction."""


async def _run_tool(name: str, impl: Callable[[], Awaitable[dict]]) -> dict:
    """Run a tool body, translating failures to safe client-facing errors.

    Guardrail refusals (HTTPException) carry visitor-facing detail strings;
    surface them. Cancellation propagates (budget handling is the impl's
    job). Everything else is logged server-side and replaced."""
    try:
        return await impl()
    except (_SafeToolError, asyncio.CancelledError):
        raise
    except HTTPException as exc:
        raise _SafeToolError(str(exc.detail)) from exc
    except Exception as exc:
        logger.exception("Unexpected error in MCP tool %s", name)
        raise _SafeToolError(UNEXPECTED_ERROR_MESSAGE) from exc


def mcp_visitor_id(client_ip: str, secret: str) -> str:
    """Stable per-client-IP visitor identity for MCP callers: UUID-shaped so
    it fits every store key and log path, keyed with a server secret so the
    mapping is not externally computable."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"mcp-visitor:{secret}:{client_ip}"))


def _visitor_identity(request: Request, settings: Settings) -> str | None:
    """The visitor id to bind quotas to, or None to mint a fresh one when the
    client IP is not trustworthy (module docstring)."""
    if not (settings.trust_proxy_headers or settings.allow_untrusted_client_ips):
        return None
    return mcp_visitor_id(get_client_ip(request, settings), settings.session_hash_secret)


def _tool_request() -> Request:
    scope = _current_scope.get()
    if scope is None:
        raise _SafeToolError(UNEXPECTED_ERROR_MESSAGE)
    return Request(scope)


async def _ask_impl(question: str, session_id: str | None) -> dict:
    request = _tool_request()
    settings = app_settings(request)
    try:
        payload = ChatRequest(message=question, session_id=session_id)
    except ValidationError as exc:
        raise _SafeToolError(
            "Invalid arguments: session_id must be at most 100 characters."
        ) from exc
    result = await run_json_chat_turn(
        payload, request, get_session_store(), settings, rag_pipeline(request),
        visitor_id=_visitor_identity(request, settings),
    )
    return {
        "reply": result.reply,
        "session_id": result.session_id,
        "sources": [source["title"] for source in result.sources],
        "used_rag": result.used_rag,
    }


async def _analyze_fit_impl(job_description: str, session_id: str | None) -> dict:
    request = _tool_request()
    settings = app_settings(request)
    try:
        payload = JDMatchRequest(jd_text=job_description, session_id=session_id)
    except ValidationError as exc:
        raise _SafeToolError(
            "Invalid arguments: job_description must not be empty and "
            "session_id must be at most 100 characters."
        ) from exc
    analysis, turn_session_id, fit_map = await run_json_jd_turn(
        payload, request, get_session_store(), settings,
        visitor_id=_visitor_identity(request, settings),
    )
    result: dict[str, Any] = {"analysis": analysis, "session_id": turn_session_id}
    if fit_map:
        result["requirement_map"] = fit_map
    return result


def build_mcp_server():
    """FastMCP server with three read-only tools: get_resume (data-only),
    ask, and analyze_fit (both guarded and metered like the page)."""
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    server = FastMCP(
        "dakota-resume",
        instructions=(
            "Dakota Radigan's resume agent. Call get_resume for the full "
            "structured resume JSON (experience, projects, skills, education, "
            "certifications). Call ask to put a question to the resume agent "
            "and analyze_fit to get a fit analysis for a job description; "
            "both are rate-limited and quota-bound exactly like the web page. "
            "Pass the returned session_id back to continue a conversation."
        ),
        stateless_http=True,
    )
    # The sub-app is mounted at /mcp by the parent app; serve at its root.
    server.settings.streamable_http_path = "/"
    # The SDK's DNS-rebinding protection rejects any Host not on its
    # allowlist (default: localhost only) with 421, including the real
    # domain. This server is public, unauthenticated, and guarded per call,
    # so rebinding protection defends nothing; disable it rather than chase
    # the domain list.
    server.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )

    @server.tool()
    def get_resume() -> dict:
        """Dakota Radigan's full resume as structured JSON (phone number excluded)."""
        return load_resume_json_public()

    @server.tool()
    async def ask(question: str, session_id: str | None = None) -> dict:
        """Ask Dakota's resume agent a question and get its answer.

        Subject to the same rate limits and free-turn quota as the chat on
        the page. Pass the returned session_id back to continue a
        conversation."""
        return await _run_tool("ask", lambda: _ask_impl(question, session_id))

    @server.tool()
    async def analyze_fit(job_description: str, session_id: str | None = None) -> dict:
        """Analyze Dakota's fit for a pasted job description.

        Subject to the same daily fit-analysis budget as the page. The job
        description is treated as untrusted data, never as instructions.
        Includes a per-requirement evidence map when the Jev judge is
        configured."""
        return await _run_tool(
            "analyze_fit", lambda: _analyze_fit_impl(job_description, session_id)
        )

    return server


class McpOrBrowser:
    """ASGI wrapper (a class instance so Starlette treats it as an ASGI
    app, not a GET-only request handler). It stashes the request scope for
    the tools, and sends a human opening /mcp in a browser to the connect
    instructions instead of a bare JSON-RPC "Not Acceptable" error. Real
    MCP clients GET with Accept: text/event-stream."""

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
        token = _current_scope.set(scope)
        try:
            await self.endpoint(scope, receive, send)
        finally:
            _current_scope.reset(token)

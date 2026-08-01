"""Application factory and ASGI entrypoint (``uvicorn app.main:app``)."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI
from starlette.routing import Route as StarletteRoute
from starlette.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.llm import warn_on_suspicious_model_ids
from app.logging_setup import configure_logging
from app.mcp_server import McpOrBrowser, build_mcp_server
from app.middleware import install_middleware
from app.retrieval import initialize_rag
from app.routes import admin, chat, feedback, health, jd_match, resume, unlock
from app.session_store import get_session_store

logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def _log_startup_warnings(settings: Settings) -> None:
    warn_on_suspicious_model_ids(settings)

    if settings.environment not in {"development", "test", "staging", "production"}:
        # The exact string "production" is load-bearing: it gates the cookie
        # Secure flag, CORS credentialed origins, and the admin loopback fallback.
        # An unrecognized value (e.g. a "prod" typo meant to be production)
        # silently downgrades all three to their non-prod (less safe) behavior,
        # so surface it loudly at startup.
        logger.warning(
            "ENVIRONMENT=%r is not a recognized value (development, test, "
            "staging, production); the Secure cookie flag, CORS credentials, and "
            "admin loopback fallback all key off the exact value 'production'.",
            settings.environment,
        )

    if settings.per_ip_daily_limit > 0 and not settings.trust_proxy_headers:
        # The per-IP daily cap needs the real client IP; without a trusted proxy
        # header every visitor collapses to the proxy IP, so the cap fails open
        # (disabled) rather than locking out the whole site. Behind Railway, set
        # TRUST_PROXY_HEADERS=true to activate it.
        logger.warning(
            "PER_IP_DAILY_LIMIT=%d is set but TRUST_PROXY_HEADERS is off, so the "
            "per-IP cap is INACTIVE (no reliable client IP behind a proxy). Set "
            "TRUST_PROXY_HEADERS=true to enforce it.",
            settings.per_ip_daily_limit,
        )


def build_app() -> FastAPI:
    configure_logging()
    mcp_server = build_mcp_server()
    mcp_asgi_app = mcp_server.streamable_http_app()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        # The MCP session manager requires a running lifespan; the session
        # store is closed on shutdown.
        async with mcp_server.session_manager.run():
            yield
        await get_session_store().close()

    app = FastAPI(
        title="Resume Assistant",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    settings = get_settings()
    _log_startup_warnings(settings)

    # Snapshot of settings for route handlers (see app.dependencies).
    app.state.settings = settings
    app.state.reindex_status = {
        "running": False,
        "started_at": None,
        "finished_at": None,
        "last_result": None,
        "last_error": None,
    }
    # Initialize RAG pipeline on startup and store in app.state
    app.state.rag_pipeline = initialize_rag(settings)

    install_middleware(app, settings)

    app.include_router(health.router)
    app.include_router(admin.router)
    app.include_router(chat.router)
    app.include_router(jd_match.router)
    app.include_router(resume.router)
    app.include_router(unlock.router)
    app.include_router(feedback.router)

    # MCP endpoint (streamable HTTP), registered before the "/" static
    # catch-all. The SDK's Starlette sub-app holds a single ASGI route;
    # re-root it at /mcp directly — a Mount would 405 bare `POST /mcp`
    # (empty-remainder mounts can only slash-redirect GETs). Data-only —
    # see app.mcp_server.
    app.router.routes.append(
        StarletteRoute(
            "/mcp",
            endpoint=McpOrBrowser(mcp_asgi_app.routes[0].endpoint),
            name="mcp",
        )
    )

    # Serve the frontend files
    if FRONTEND_DIR.exists():
        app.mount(
            "/",
            StaticFiles(directory=FRONTEND_DIR, html=True),
            name="frontend",
        )

    return app


app = build_app()

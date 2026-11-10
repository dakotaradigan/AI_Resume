"""Admin endpoints: cache clearing, RAG reindexing, analytics export, and
the client-IP report."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app import chat_service, content, resume_pdf
from app.dependencies import app_settings, rag_pipeline
from app.identity import get_client_ip
from app.routes.health import clear_collection_check
from app.security import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")

# The headers a proxy may carry the visitor's address in. The report shows
# each as this app received it.
CLIENT_ADDRESS_HEADERS = (
    "x-real-ip",
    "x-forwarded-for",
    "forwarded",
    "cf-connecting-ip",
    "true-client-ip",
    "x-envoy-external-address",
)

# Reindex lock: prevent concurrent re-indexing operations (wastes API costs).
_reindex_lock: asyncio.Lock | None = None


def get_reindex_lock() -> asyncio.Lock:
    """Get or create the global reindex lock."""
    global _reindex_lock
    if _reindex_lock is None:
        _reindex_lock = asyncio.Lock()
    return _reindex_lock


def clear_all_caches() -> None:
    """Drop every process-local content cache (prompts, resume, PDF, starters)."""
    content.clear_caches()
    resume_pdf.render_resume_pdf.cache_clear()
    chat_service.clear_starter_cache()


@router.post("/cache/clear")
async def clear_cache(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, str]:
    """
    Clear all cached data (system prompt, resume context).

    Use this endpoint after updating resume.json or system_prompt.txt
    to refresh the cache without restarting the server.
    """
    require_admin(request, x_admin_token, app_settings(request))

    clear_all_caches()
    logger.info("Cache cleared: prompts, resume_context, and starter responses")
    return {
        "status": "success",
        "message": "Cache cleared. Fresh data will be loaded on next request.",
    }


@router.post("/rag/reindex")
async def reindex_rag(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """
    Force a verified in-place refresh of the RAG collection.

    Use this endpoint after updating resume.json or other source data to
    refresh the vector search index without restarting the server.

    Authentication:
    - Development: No token required
    - Production: Requires X-Admin-Token header matching ADMIN_TOKEN env var

    Concurrency Protection:
    - Only one reindex operation allowed at a time (prevents wasted API costs)
    - Returns 429 if reindex already in progress

    Returns:
        Operation details including old/new chunk counts and status
    """
    settings = app_settings(request)
    require_admin(request, x_admin_token, settings)

    # Validate RAG is enabled
    pipeline = rag_pipeline(request)
    if pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="RAG pipeline not initialized (check USE_RAG and API keys in settings).",
        )

    # Prevent concurrent re-indexing (would waste API costs on duplicate embeddings)
    reindex_lock = get_reindex_lock()
    if reindex_lock.locked():
        raise HTTPException(
            status_code=429,
            detail="Re-indexing already in progress. Please wait for it to complete.",
        )

    # Perform re-indexing with async lock protection
    async with reindex_lock:
        try:
            resume_path = settings.data_dir / "resume.json"
            request.app.state.reindex_status.update(
                {
                    "running": True,
                    "started_at": time.time(),
                    "finished_at": None,
                    "last_error": None,
                }
            )
            # Run blocking operation in thread pool (prevents freezing other requests)
            result = await asyncio.to_thread(
                pipeline.reindex,
                resume_path,
                settings.data_dir / "projects",
            )
            request.app.state.reindex_status.update(
                {
                    "running": False,
                    "finished_at": time.time(),
                    "last_result": result,
                }
            )
            # Clear cached resume data so subsequent requests use fresh data,
            # and the cached collection state so /health/rag shows the new index.
            clear_all_caches()
            clear_collection_check(request.app)
            logger.info(f"RAG re-index completed: {result['message']}")
            return result
        except Exception as exc:
            logger.exception("Failed to re-index RAG pipeline")
            request.app.state.reindex_status.update(
                {
                    "running": False,
                    "finished_at": time.time(),
                    "last_error": str(exc),
                }
            )
            raise HTTPException(
                status_code=500,
                detail=f"Re-indexing failed: {str(exc)}",
            ) from exc


@router.get("/rag/reindex/status")
async def reindex_status(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_admin(request, x_admin_token, app_settings(request))
    return request.app.state.reindex_status


@router.get("/analytics/export")
async def export_analytics(
    request: Request,
    x_admin_token: str | None = Header(default=None),
    file: Literal["queries", "feedback"] = "queries",
) -> PlainTextResponse:
    """Export analytics data (JSONL). Use ?file=queries or ?file=feedback."""
    require_admin(request, x_admin_token, app_settings(request))
    from analytics.analytics import ANALYTICS_FILE, FEEDBACK_FILE

    path = ANALYTICS_FILE if file == "queries" else FEEDBACK_FILE
    if not path.exists():
        return PlainTextResponse("", media_type="application/jsonl")
    return PlainTextResponse(
        path.read_text(encoding="utf-8"), media_type="application/jsonl"
    )



@router.get("/client-ip")
async def client_ip_report(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """How this request's client address reached the app.

    Every rate limit and per-IP cap keys on get_client_ip, and that is only
    as good as CLIENT_IP_HEADER. Which header a platform puts the visitor's
    address in, and whether it replaces a value the caller sent, differs
    between platforms and has changed over time, so measure it:

    1. Call this from a machine whose public address you know. The header
       whose value is that address is the candidate.
    2. Call it again sending made-up values in the candidate headers. A
       header that comes back with your made-up value is one the caller
       controls and must not be trusted.

    Admin-only: the values include the platform's internal addresses.
    """
    settings = app_settings(request)
    require_admin(request, x_admin_token, settings)
    return {
        "resolved_client_ip": get_client_ip(request, settings),
        "trust_proxy_headers": settings.trust_proxy_headers,
        "client_ip_header": settings.client_ip_header,
        "socket_peer": request.client.host if request.client else None,
        "received": {name: request.headers.get(name) for name in CLIENT_ADDRESS_HEADERS},
    }

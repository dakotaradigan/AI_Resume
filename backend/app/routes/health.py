"""Health and diagnostics endpoints."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from anthropic import AnthropicError
from fastapi import APIRouter, Header, Request

from app.dependencies import app_settings, rag_pipeline
from app.llm import make_anthropic_client
from app.security import require_admin

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/rag")
async def rag_health(request: Request) -> dict[str, Any]:
    """Check RAG pipeline status for monitoring."""
    settings = app_settings(request)
    pipeline = rag_pipeline(request)
    collection_exists: bool | None = None
    points_count: int | None = None
    keyword_documents_count = 0
    keyword_index_ready = False
    corpus_current = False
    dense_retrieval_status = "not_initialized"

    if pipeline is not None:
        keyword_documents_count = int(
            getattr(pipeline, "keyword_documents_count", 0) or 0
        )
        keyword_index_ready = bool(
            getattr(pipeline, "keyword_index_ready", False)
        )
        corpus_current = bool(getattr(pipeline, "corpus_current", False))
        dense_retrieval_status = str(
            getattr(pipeline, "dense_retrieval_status", "not_tested")
        )
        try:
            collection_exists = await asyncio.to_thread(
                pipeline.qdrant_client.collection_exists,
                collection_name=pipeline.collection_name,
            )
            if collection_exists:
                count_result = await asyncio.to_thread(
                    pipeline.qdrant_client.count,
                    collection_name=pipeline.collection_name,
                    exact=True,
                )
                points_count = int(getattr(count_result, "count", 0) or 0)
            else:
                points_count = 0
        except Exception:
            logger.exception("Failed to check RAG collection health")

    vector_db_live = bool(collection_exists and (points_count or 0) > 0)
    indexes_ready = bool(
        vector_db_live
        and keyword_index_ready
        and points_count == keyword_documents_count
        and corpus_current
    )
    # A populated collection is not an end-to-end retrieval check. Report
    # ready only after at least one dense query has actually succeeded.
    retrieval_ready = indexes_ready and dense_retrieval_status == "healthy"
    return {
        "rag_enabled": settings.use_rag,
        "rag_initialized": pipeline is not None,
        "qdrant_configured": bool(settings.qdrant_url),
        "mode": "rag" if settings.use_rag and pipeline is not None else "static_fallback",
        "collection_exists": collection_exists,
        "points_count": points_count,
        "vector_db_live": vector_db_live,
        "keyword_documents_count": keyword_documents_count,
        "keyword_index_ready": keyword_index_ready,
        "corpus_current": corpus_current,
        "indexes_ready": indexes_ready,
        "dense_retrieval_status": dense_retrieval_status,
        "retrieval_ready": retrieval_ready,
    }


@router.get("/health/models")
async def models_health(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Live-check each configured model against the Anthropic API.

    'Deploy succeeded' says nothing about whether the account can call
    the configured models; this endpoint does, without spending tokens.

    Admin-gated: each call issues live upstream Anthropic requests and
    reflects provider error detail, so it is an operator diagnostic, not a
    public endpoint (anonymous callers could otherwise use it to amplify
    upstream calls and enumerate model/config).
    """
    settings = app_settings(request)
    require_admin(request, x_admin_token, settings)
    client = make_anthropic_client(settings)
    results: dict[str, Any] = {}
    for env_name, model_id in (
        ("ANTHROPIC_MODEL", settings.anthropic_model),
        ("ANTHROPIC_MODEL_SIMPLE", settings.anthropic_model_simple),
        ("ANTHROPIC_ROUTER_MODEL", settings.anthropic_router_model),
    ):
        try:
            await client.models.retrieve(model_id)
            results[env_name] = {"model": model_id, "status": "ok"}
        except AnthropicError as exc:
            results[env_name] = {
                "model": model_id,
                "status": "error",
                "detail": str(exc)[:300],
            }
        except Exception as exc:  # pragma: no cover - unexpected transport errors
            results[env_name] = {
                "model": model_id,
                "status": "error",
                "detail": f"{type(exc).__name__}: {exc}"[:300],
            }
    return results

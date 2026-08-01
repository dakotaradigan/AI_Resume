"""RAG pipeline startup and per-turn context retrieval."""

from __future__ import annotations

import logging
from typing import Any

from rag import RAGPipeline, initialize_rag_pipeline

from app.config import Settings
from app.content import load_resume_context

logger = logging.getLogger(__name__)


def initialize_rag(settings: Settings) -> RAGPipeline | None:
    """
    Initialize RAG pipeline on application startup.

    Returns the initialized pipeline, or None if disabled or failed (the app
    then serves static resume context).
    """
    if not settings.use_rag:
        logger.info("RAG disabled in settings, using static resume context")
        return None

    if not settings.openai_api_key:
        logger.warning("OpenAI API key not configured, RAG disabled (falling back to static context)")
        return None

    if not (settings.qdrant_url or "").strip():
        logger.warning("QDRANT_URL not configured, RAG disabled (falling back to static context)")
        return None

    try:
        resume_path = settings.data_dir / "resume.json"
        logger.info("Initializing RAG pipeline...")
        pipeline = initialize_rag_pipeline(
            openai_api_key=settings.openai_api_key,
            resume_path=resume_path,
            qdrant_url=settings.qdrant_url,
            qdrant_api_key=settings.qdrant_api_key,
            projects_dir=settings.data_dir / "projects",
        )
        logger.info("✅ RAG pipeline initialized successfully")
        return pipeline

    except Exception:
        logger.exception("Failed to initialize RAG pipeline, falling back to static context")
        return None


def retrieve_rag_context(
    rag_pipeline: RAGPipeline | None,
    query: str,
    limit: int = 4,
    score_threshold: float = 0.30,
) -> tuple[str, bool, list[dict[str, Any]]]:
    """
    Retrieve relevant resume context using RAG pipeline.

    Args:
        rag_pipeline: Initialized RAG pipeline (None if disabled)
        query: User's message to search for relevant context
        limit: Maximum number of chunks to retrieve
        score_threshold: Minimum similarity score (0-1)

    Returns:
        (context, used_rag, sources) — sources is [{"title": str, "score": float}]
        for the retrieved chunks. The non-streaming API maps these to bare
        titles to keep the ChatResponse.sources contract (list[str]) unchanged.
    """
    if rag_pipeline is None:
        logger.warning("RAG pipeline not initialized, falling back to static context")
        return load_resume_context(), False, []

    try:
        results = rag_pipeline.search(query, limit=limit, score_threshold=score_threshold)

        if not results:
            logger.info(f"No RAG results found for query (threshold={score_threshold}), using static context")
            return load_resume_context(), False, []

        # Format retrieved chunks into context string
        context_parts = []
        sources = []
        for idx, result in enumerate(results, 1):
            context_parts.append(
                f"[Context {idx}: {result['title']}]\n{result['text']}"
            )
            sources.append({
                "title": result["title"],
                "score": round(float(result.get("score") or 0.0), 3),
            })

        return "\n\n".join(context_parts), True, sources

    except Exception:
        logger.exception("RAG retrieval failed, falling back to static context")
        return load_resume_context(), False, []

"""Accessors for per-app state shared by route handlers."""

from __future__ import annotations

from fastapi import Request
from rag import RAGPipeline

from app.config import Settings


def app_settings(request: Request) -> Settings:
    """The Settings snapshot captured when the app was built."""
    return request.app.state.settings


def rag_pipeline(request: Request) -> RAGPipeline | None:
    """The RAG pipeline initialized at startup, or None when disabled/failed."""
    return getattr(request.app.state, "rag_pipeline", None)

"""RAG pipeline: chunking, embedding, hybrid retrieval, and indexing.

Modules:
- ``chunking``: turns resume JSON and project markdown into ``DocumentChunk``s.
- ``keyword_index``: in-process BM25 index over chunk payloads.
- ``pipeline``: ``RAGPipeline`` (Qdrant + OpenAI embeddings + rank fusion).
"""

from rag.chunking import (
    DocumentChunk,
    build_corpus,
    chunk_project_docs,
    chunk_resume_data,
)
from rag.pipeline import RAGPipeline, initialize_rag_pipeline

__all__ = [
    "DocumentChunk",
    "RAGPipeline",
    "build_corpus",
    "chunk_project_docs",
    "chunk_resume_data",
    "initialize_rag_pipeline",
]

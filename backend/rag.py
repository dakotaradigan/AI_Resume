"""
RAG Pipeline: Document chunking, embedding, and retrieval for Resume Assistant.

This module handles:
1. Chunking resume data into semantic units
2. Generating embeddings with OpenAI text-embedding-3-small
3. Indexing chunks into Qdrant
4. Semantic search retrieval
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI, OpenAIError
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """Represents a chunk of resume data with metadata."""

    text: str
    chunk_type: str  # "personal", "experience", "project", "skills"
    title: str
    timeframe: str | None = None
    tags: list[str] | None = None


class RAGPipeline:
    """Manages the RAG pipeline: chunking, embedding, indexing, and retrieval."""

    def __init__(
        self,
        openai_api_key: str,
        qdrant_url: str,
        qdrant_api_key: str = "",
        embedding_model: str = "text-embedding-3-small",
        collection_name: str = "resume",
    ):
        """
        Initialize RAG pipeline.

        Args:
            openai_api_key: OpenAI API key for embeddings
            qdrant_url: Qdrant URL (required). For demos, use Qdrant Cloud.
            qdrant_api_key: Qdrant API key (used for Qdrant Cloud)
            embedding_model: OpenAI embedding model to use
            collection_name: Qdrant collection name
        """
        # Lazy-init the OpenAI client to avoid eager network/SSL setup during app startup
        # and to keep offline tests (that mock embed_text) fully offline.
        self._openai_api_key = openai_api_key
        self._openai_client: OpenAI | None = None
        self.embedding_model = embedding_model
        self.collection_name = collection_name

        qdrant_url = (qdrant_url or "").strip()
        if not qdrant_url:
            raise ValueError("qdrant_url is required (set QDRANT_URL).")

        logger.info(f"Connecting to Qdrant at {qdrant_url}")
        self.qdrant_client = QdrantClient(
            url=qdrant_url,
            api_key=qdrant_api_key or None,
        )

        self._initialize_collection()

    def _get_openai_client(self) -> OpenAI:
        if self._openai_client is None:
            self._openai_client = OpenAI(api_key=self._openai_api_key)
        return self._openai_client

    def _initialize_collection(self) -> None:
        """Create Qdrant collection if it doesn't exist."""
        collections = self.qdrant_client.get_collections().collections
        collection_names = [c.name for c in collections]

        if self.collection_name not in collection_names:
            # text-embedding-3-small produces 1536-dimensional vectors
            self.qdrant_client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
            )
            logger.info(f"Created collection: {self.collection_name}")
        else:
            logger.info(f"Collection already exists: {self.collection_name}")

    def chunk_resume_data(self, resume_path: Path) -> list[DocumentChunk]:
        """
        Chunk resume JSON into semantic units.

        Strategy:
        - Personal info: 1 chunk
        - Each job experience: 1 chunk (with all achievements)
        - Each project: 1-3 chunks depending on detail
        - Skills: 1 chunk

        Args:
            resume_path: Path to resume.json

        Returns:
            List of DocumentChunk objects
        """
        with open(resume_path, encoding="utf-8") as f:
            data = json.load(f)

        chunks: list[DocumentChunk] = []

        # Personal info chunk
        personal = data.get("personal", {})
        if personal:
            text_parts = [
                f"Name: {personal.get('name', '')}",
                f"Title: {personal.get('title', '')}",
                f"Location: {personal.get('location', '')}",
                f"Summary: {personal.get('summary', '')}",
                f"Email: {personal.get('email', '')}",
                f"LinkedIn: {personal.get('linkedin', '')}",
                f"Phone: {personal.get('phone', '')}",
            ]
            text = "\n".join([p for p in text_parts if p and not p.endswith(": ")])
            chunks.append(
                DocumentChunk(
                    text=text,
                    chunk_type="personal",
                    title="Personal Information",
                    tags=["contact", "summary"],
                )
            )

        # Experience chunks (one per job)
        for exp in data.get("experience", []):
            achievements = exp.get("achievements", [])
            achievements_text = "\n".join([f"- {a}" for a in achievements])
            text = f"""
Role: {exp.get('role', '')}
Company: {exp.get('company', '')}
Duration: {exp.get('duration', '')}
Description: {exp.get('description', '')}

Achievements:
{achievements_text}

Technologies: {', '.join(exp.get('technologies', []))}
            """.strip()

            chunks.append(
                DocumentChunk(
                    text=text,
                    chunk_type="experience",
                    title=f"{exp.get('role', '')} at {exp.get('company', '')}",
                    timeframe=exp.get("duration", ""),
                    tags=exp.get("technologies", []),
                )
            )

        # Project chunks
        for proj in data.get("projects", []):
            # Main project chunk (overview)
            highlights = proj.get("highlights", [])
            highlights_text = "\n".join([f"- {h}" for h in highlights])

            main_text = f"""
Project: {proj.get('name', '')}
Tagline: {proj.get('tagline', '')}

Description:
{proj.get('description', '')}

Key Highlights:
{highlights_text}

Problem Solved:
{proj.get('problem_solved', '')}

Impact:
{proj.get('impact', '')}

Context: {proj.get('context', '')}
Tech Stack: {', '.join(proj.get('tech_stack', []))}
            """.strip()

            chunks.append(
                DocumentChunk(
                    text=main_text,
                    chunk_type="project",
                    title=proj.get("name", ""),
                    timeframe=proj.get("timeframe", ""),
                    tags=proj.get("tech_stack", []),
                )
            )

            # Architecture details chunk (if present)
            arch_details = proj.get("architecture_details")
            if arch_details:
                arch_text_parts = [
                    f"Project: {proj.get('name', '')} - Architecture Details",
                    "",
                    f"Frontend: {arch_details.get('frontend', '')}",
                    f"Backend: {arch_details.get('backend', '')}",
                    f"AI Orchestration: {arch_details.get('ai_orchestration', '')}",
                    f"Data Layer: {arch_details.get('data_layer', '')}",
                    "",
                    "Core Capabilities:",
                ]
                for cap in arch_details.get("core_capabilities", []):
                    arch_text_parts.append(f"- {cap}")

                chunks.append(
                    DocumentChunk(
                        text="\n".join(arch_text_parts),
                        chunk_type="project",
                        title=f"{proj.get('name', '')} - Architecture",
                        timeframe=proj.get("timeframe", ""),
                        tags=["architecture"] + proj.get("tech_stack", []),
                    )
                )

        # Skills chunk
        skills = data.get("skills", {})
        if skills:
            skills_parts = []
            for category, skill_list in skills.items():
                skills_parts.append(f"{category.replace('_', ' ').title()}:")
                skills_parts.append(", ".join(skill_list))
                skills_parts.append("")

            chunks.append(
                DocumentChunk(
                    text="\n".join(skills_parts).strip(),
                    chunk_type="skills",
                    title="Skills and Expertise",
                    tags=["skills", "technical", "leadership"],
                )
            )

        logger.info(f"Created {len(chunks)} document chunks")
        return chunks

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((OpenAIError, TimeoutError)),
    )
    def embed_text(self, text: str) -> list[float]:
        """
        Generate embedding for text using OpenAI.

        Automatically retries up to 3 times with exponential backoff
        on transient failures (network errors, rate limits, timeouts).
        """
        try:
            response = self._get_openai_client().embeddings.create(
                model=self.embedding_model,
                input=text,
                timeout=10.0,  # Per-request timeout
            )
            return response.data[0].embedding
        except OpenAIError as exc:
            logger.warning(f"OpenAI embedding request failed (will retry if attempts remain): {exc}")
            raise  # Let tenacity handle retry

    def index_chunks(self, chunks: list[DocumentChunk]) -> None:
        """Index chunks into Qdrant with embeddings."""
        points = []

        for idx, chunk in enumerate(chunks):
            # Generate embedding
            embedding = self.embed_text(chunk.text)

            # Create point with metadata
            point = PointStruct(
                id=idx,
                vector=embedding,
                payload={
                    "text": chunk.text,
                    "type": chunk.chunk_type,
                    "title": chunk.title,
                    "timeframe": chunk.timeframe or "",
                    "tags": chunk.tags or [],
                },
            )
            points.append(point)

        # Batch upload to Qdrant
        self.qdrant_client.upsert(collection_name=self.collection_name, points=points)
        logger.info(f"Indexed {len(points)} chunks into Qdrant")

    def search(
        self, query: str, limit: int = 3, score_threshold: float = 0.7
    ) -> list[dict[str, Any]]:
        """
        Search for relevant chunks using semantic similarity.

        Args:
            query: User's question
            limit: Max number of results to return
            score_threshold: Minimum similarity score (0-1)

        Returns:
            List of relevant chunks with metadata
        """
        # Embed the query
        query_embedding = self.embed_text(query)

        # Search Qdrant
        results = self.qdrant_client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding,
            limit=limit,
            score_threshold=score_threshold,
        )

        # Format results
        formatted_results = []
        for result in results:
            formatted_results.append(
                {
                    "text": result.payload["text"],
                    "title": result.payload["title"],
                    "type": result.payload["type"],
                    "score": result.score,
                    "timeframe": result.payload.get("timeframe", ""),
                }
            )

        return formatted_results


def initialize_rag_pipeline(
    openai_api_key: str,
    resume_path: Path,
    qdrant_url: str,
    qdrant_api_key: str = "",
) -> RAGPipeline:
    """
    Initialize and index the RAG pipeline.

    Args:
        openai_api_key: OpenAI API key
        resume_path: Path to resume.json
        qdrant_url: Qdrant URL (required)
        qdrant_api_key: Qdrant API key (used for Qdrant Cloud)

    Returns:
        Initialized RAGPipeline
    """
    # Initialize pipeline
    pipeline = RAGPipeline(
        openai_api_key=openai_api_key,
        qdrant_url=qdrant_url,
        qdrant_api_key=qdrant_api_key,
    )

    # Check if collection already has data (avoid re-indexing on every startup)
    collection_info = pipeline.qdrant_client.get_collection(pipeline.collection_name)
    points_count = collection_info.points_count

    if points_count > 0:
        logger.info(f"Collection already indexed with {points_count} points, skipping re-indexing")
    else:
        logger.info("Collection empty, indexing resume data...")
        # Chunk and index resume data
        chunks = pipeline.chunk_resume_data(resume_path)
        pipeline.index_chunks(chunks)

    return pipeline

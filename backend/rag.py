"""
RAG Pipeline: Document chunking, embedding, and retrieval for Resume Assistant.

This module handles:
1. Chunking structured resume data and project documents into source-aligned units
2. Generating embeddings with OpenAI text-embedding-3-small
3. Indexing chunks and payloads into Qdrant
4. Building an in-process BM25 keyword index
5. Fusing semantic and lexical rankings with reciprocal rank fusion
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
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

_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")
_RRF_K = 60


@dataclass
class DocumentChunk:
    """Represents a chunk of resume or project source data with metadata."""

    text: str
    chunk_type: str  # e.g. personal, experience, project, project_doc, skills
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
        self._keyword_documents: list[dict[str, Any]] = []
        self._term_frequencies: list[Counter[str]] = []
        self._document_frequencies: Counter[str] = Counter()
        self._average_document_length = 0.0

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
        """
        Create Qdrant collection if it doesn't exist (idempotent).

        Uses try/except pattern to handle race conditions where multiple
        workers might try to create the same collection simultaneously.
        """
        try:
            # text-embedding-3-small produces 1536-dimensional vectors
            self.qdrant_client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
            )
            logger.info(f"Created collection: {self.collection_name}")
        except Exception as exc:
            exc_str = str(exc).lower()
            # Collection already exists - this is expected in race conditions
            if "already exists" in exc_str or "409" in exc_str:
                logger.info(f"Collection already exists: {self.collection_name}")
            else:
                # Unexpected error - re-raise
                raise

    @staticmethod
    def chunk_resume_data(resume_path: Path) -> list[DocumentChunk]:
        """
        Chunk resume JSON into semantic units.

        Strategy:
        - Personal info: 1 chunk
        - Each job experience: 1 chunk (with all achievements)
        - Each project: 1-3 chunks depending on detail
        - Skills: 1 chunk
        - Education: 1 chunk
        - Certifications: 1 chunk

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
                # Phone intentionally excluded - PII should not be in RAG context
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

            # Add distinguishing context early in the chunk
            main_text = f"""
Project: {proj.get('name', '')}
Context: {proj.get('context', '')}
Timeframe: {proj.get('timeframe', '')}
Tagline: {proj.get('tagline', '')}

Description:
{proj.get('description', '')}

Key Highlights:
{highlights_text}

Problem Solved:
{proj.get('problem_solved', '')}

Impact:
{proj.get('impact', '')}

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
                # Add distinguishing context at the beginning
                arch_text_parts = [
                    f"Project: {proj.get('name', '')} - Architecture Details",
                    f"Context: {proj.get('context', '')}",
                    f"Timeframe: {proj.get('timeframe', '')}",
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

        # Education chunk
        education = data.get("education", [])
        if education:
            edu_parts = []
            for edu in education:
                edu_lines = [
                    f"Degree: {edu.get('degree', '')}",
                    f"School: {edu.get('school', '')}",
                    f"Graduated: {edu.get('graduation', '')}",
                ]
                # Filter out empty values (matches personal chunk pattern)
                edu_text = "\n".join([line for line in edu_lines if line and not line.endswith(": ")])
                if edu_text:
                    edu_parts.append(edu_text)
                    edu_parts.append("")  # Spacing between degrees

            if edu_parts:
                chunks.append(
                    DocumentChunk(
                        text="\n".join(edu_parts).strip(),
                        chunk_type="education",
                        title="Education",
                        tags=["education", "academic"],
                    )
                )

        # Certifications chunk
        certifications = data.get("certifications", [])
        if certifications:
            cert_parts = []
            for cert in certifications:
                name = cert.get("name", "").strip()
                issuer = cert.get("issuer", "").strip()
                status = cert.get("status", "").strip()

                # Build cert line only if we have name or issuer
                if name or issuer:
                    cert_line = " - ".join([p for p in [name, issuer] if p])
                    if status:
                        cert_line += f" ({status})"
                    cert_parts.append(cert_line)

            if cert_parts:
                chunks.append(
                    DocumentChunk(
                        text="\n".join(cert_parts).strip(),
                        chunk_type="certifications",
                        title="Certifications",
                        tags=["certifications", "credentials"],
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

        # Filter empty chunks to avoid wasting embedding API calls
        valid_chunks = [c for c in chunks if c.text and c.text.strip()]
        if len(valid_chunks) < len(chunks):
            logger.warning(
                f"Filtered {len(chunks) - len(valid_chunks)} empty chunks "
                f"(processing {len(valid_chunks)} valid chunks)"
            )

        payloads: list[dict[str, Any]] = []
        for idx, chunk in enumerate(valid_chunks):
            # Generate embedding
            embedding = self.embed_text(chunk.text)

            # Create point with metadata
            payload = {
                "text": chunk.text,
                "type": chunk.chunk_type,
                "title": chunk.title,
                "timeframe": chunk.timeframe or "",
                "tags": chunk.tags or [],
            }
            point = PointStruct(
                id=idx,
                vector=embedding,
                payload=payload,
            )
            points.append(point)
            payloads.append(payload)

        # Batch upload to Qdrant
        self.qdrant_client.upsert(collection_name=self.collection_name, points=points)
        self._build_keyword_index(payloads)
        logger.info(f"Indexed {len(points)} chunks into Qdrant")

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return _TOKEN_RE.findall(text.lower())

    def _build_keyword_index(self, payloads: list[dict[str, Any]]) -> None:
        """Build the in-process BM25 index from Qdrant-compatible payloads."""
        term_frequencies: list[Counter[str]] = []
        document_frequencies: Counter[str] = Counter()

        total_tokens = 0
        for payload in payloads:
            tokens = self._tokenize(str(payload.get("text", "")))
            frequencies = Counter(tokens)
            term_frequencies.append(frequencies)
            document_frequencies.update(frequencies.keys())
            total_tokens += len(tokens)

        average_document_length = total_tokens / len(payloads) if payloads else 0.0
        self._keyword_documents = payloads
        self._term_frequencies = term_frequencies
        self._document_frequencies = document_frequencies
        self._average_document_length = average_document_length

    def _rebuild_keyword_index_from_qdrant(self) -> None:
        """Restore the BM25 index from all stored payloads without re-embedding."""
        payloads: list[dict[str, Any]] = []
        offset: Any = None

        while True:
            records, next_offset = self.qdrant_client.scroll(
                collection_name=self.collection_name,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for record in records:
                if record.payload:
                    payloads.append(dict(record.payload))
            if next_offset is None:
                break
            offset = next_offset

        self._build_keyword_index(payloads)
        logger.info(f"Rebuilt keyword index from {len(payloads)} stored chunks")

    def _bm25_rank(self, query: str) -> list[tuple[int, float]]:
        """Return positive-score document indexes ranked by BM25."""
        query_tokens = self._tokenize(query)
        document_count = len(self._keyword_documents)
        if not query_tokens or not document_count or self._average_document_length == 0:
            return []

        scores = [0.0] * document_count
        for term in query_tokens:
            document_frequency = self._document_frequencies.get(term, 0)
            if document_frequency == 0:
                continue
            inverse_document_frequency = math.log(
                1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            for index, frequencies in enumerate(self._term_frequencies):
                term_frequency = frequencies.get(term, 0)
                if term_frequency == 0:
                    continue
                document_length = sum(frequencies.values())
                length_normalization = 1 - 0.75 + (
                    0.75 * document_length / self._average_document_length
                )
                scores[index] += inverse_document_frequency * (
                    term_frequency * (1.5 + 1)
                ) / (term_frequency + 1.5 * length_normalization)

        return sorted(
            ((index, score) for index, score in enumerate(scores) if score > 0),
            key=lambda item: (-item[1], item[0]),
        )

    def search(
        self, query: str, limit: int = 4, score_threshold: float = 0.30
    ) -> list[dict[str, Any]]:
        """
        Search for relevant chunks using vector similarity and BM25 with RRF.

        Args:
            query: User's question
            limit: Max number of results to return
            score_threshold: Minimum Qdrant vector similarity accepted by the vector leg.
                BM25 candidates are not filtered by this threshold.

        Returns:
            List of relevant chunks with metadata
        """
        # Embed the query
        query_embedding = self.embed_text(query)

        # Search Qdrant
        response = self.qdrant_client.query_points(
            collection_name=self.collection_name,
            query=query_embedding,
            limit=limit,
            score_threshold=score_threshold,
        )

        vector_results: dict[tuple[str, str, str], dict[str, Any]] = {}
        fused_scores: dict[tuple[str, str, str], float] = {}

        for rank, result in enumerate(response.points, 1):
            payload = dict(result.payload or {})
            key = self._payload_key(payload)
            vector_results[key] = payload | {"score": float(result.score)}
            fused_scores[key] = fused_scores.get(key, 0.0) + 1 / (_RRF_K + rank)

        keyword_ranking = self._bm25_rank(query)
        keyword_ranks: dict[tuple[str, str, str], int] = {}
        keyword_results: dict[tuple[str, str, str], dict[str, Any]] = {}
        for rank, (index, _) in enumerate(keyword_ranking, 1):
            payload = self._keyword_documents[index]
            key = self._payload_key(payload)
            keyword_ranks[key] = rank
            keyword_results[key] = payload
            fused_scores[key] = fused_scores.get(key, 0.0) + 1 / (_RRF_K + rank)

        if not response.points and not keyword_ranking:
            return []

        ranked_keys = sorted(
            fused_scores,
            key=lambda key: (
                -fused_scores[key],
                keyword_ranks.get(key, math.inf),
                key,
            ),
        )[:limit]

        formatted_results = []
        for key in ranked_keys:
            payload = vector_results.get(key) or keyword_results[key]
            formatted_results.append(
                {
                    **payload,
                    "score": float(vector_results.get(key, {}).get("score", 0.0)),
                    "keyword_rank": keyword_ranks.get(key),
                }
            )
        return formatted_results

    @staticmethod
    def _payload_key(payload: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(payload.get("title", "")),
            str(payload.get("type", "")),
            str(payload.get("text", "")),
        )

    def reindex(
        self, resume_path: Path, projects_dir: Path | None = None
    ) -> dict[str, Any]:
        """
        Force re-indexing of resume data.

        Deletes the existing collection and creates a fresh one with current data.
        This is useful when resume.json has been updated and changes need to be
        immediately reflected in the RAG system without restarting the backend.

        Args:
            resume_path: Path to resume.json
            projects_dir: Optional directory containing project markdown files

        Returns:
            Dictionary with operation details:
            {
                "status": "success",
                "collection_name": str,
                "old_points_count": int,
                "new_points_count": int,
                "message": str
            }
        """
        # Get current point count before deletion
        old_points_count = 0
        try:
            collection_info = self.qdrant_client.get_collection(self.collection_name)
            old_points_count = collection_info.points_count
            logger.info(f"Current collection has {old_points_count} points")
        except Exception as exc:
            # Collection doesn't exist (404) or other Qdrant error
            exc_str = str(exc).lower()
            if "not found" in exc_str or "doesn't exist" in exc_str or "404" in exc_str:
                logger.info("Collection doesn't exist yet, will create fresh")
            else:
                logger.warning(f"Could not get collection info: {exc}")

        # Delete existing collection
        try:
            self.qdrant_client.delete_collection(self.collection_name)
            logger.info(f"Deleted collection: {self.collection_name}")
        except Exception as exc:
            exc_str = str(exc).lower()
            if "not found" in exc_str or "doesn't exist" in exc_str or "404" in exc_str:
                logger.info(f"Collection {self.collection_name} didn't exist, will create fresh")
            else:
                logger.warning(f"Could not delete collection (will try to recreate): {exc}")

        # Re-create collection
        self._initialize_collection()

        # Chunk and index fresh data
        chunks = build_corpus(resume_path, projects_dir)
        self.index_chunks(chunks)

        new_points_count = len(chunks)
        message = f"Re-indexed {new_points_count} chunks (was {old_points_count})"
        logger.info(f"✅ {message}")

        return {
            "status": "success",
            "collection_name": self.collection_name,
            "old_points_count": old_points_count,
            "new_points_count": new_points_count,
            "message": message,
        }


def chunk_project_docs(projects_dir: Path) -> list[DocumentChunk]:
    """Chunk project markdown files by H2 section."""
    chunks: list[DocumentChunk] = []

    for project_path in sorted(projects_dir.glob("*.md")):
        markdown = project_path.read_text(encoding="utf-8")
        title_match = re.search(r"^#\s+(.+?)\s*$", markdown, re.MULTILINE)
        if title_match is None:
            logger.warning(f"Skipping project doc without H1 title: {project_path}")
            continue
        document_title = title_match.group(1).strip()

        sections = re.split(r"^##\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
        for index in range(1, len(sections), 2):
            section_heading = sections[index].strip()
            section_body = sections[index + 1].strip()
            section_text = f"## {section_heading}\n\n{section_body}".strip()

            if len(section_body) < 300 and chunks and chunks[-1].title.startswith(
                f"{document_title} — "
            ):
                chunks[-1].text = f"{chunks[-1].text}\n\n{section_text}"
                continue

            chunks.append(
                DocumentChunk(
                    text=f"# {document_title}\n\n{section_text}",
                    chunk_type="project_doc",
                    title=f"{document_title} — {section_heading}",
                )
            )

    logger.info(f"Created {len(chunks)} project document chunks")
    return chunks


def build_corpus(resume_path: Path, projects_dir: Path | None) -> list[DocumentChunk]:
    """Build the complete resume and project-document corpus."""
    chunks = RAGPipeline.chunk_resume_data(resume_path)
    if projects_dir is not None and projects_dir.is_dir():
        chunks.extend(chunk_project_docs(projects_dir))
    logger.info(f"Built corpus with {len(chunks)} chunks")
    return chunks


def initialize_rag_pipeline(
    openai_api_key: str,
    resume_path: Path,
    qdrant_url: str,
    qdrant_api_key: str = "",
    projects_dir: Path | None = None,
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
    try:
        collection_info = pipeline.qdrant_client.get_collection(pipeline.collection_name)
        points_count = collection_info.points_count
    except Exception as exc:
        # Collection doesn't exist yet, will be created during indexing
        exc_str = str(exc).lower()
        if "not found" in exc_str or "doesn't exist" in exc_str or "404" in exc_str:
            logger.info("Collection doesn't exist, will create and index...")
        else:
            logger.warning(f"Could not check collection status: {exc}. Will attempt to index...")
    else:
        if points_count > 0:
            pipeline._rebuild_keyword_index_from_qdrant()
            # Self-healing index: when the stored chunks differ from what the
            # current data files produce (resume.json edited, project docs
            # added), rebuild automatically instead of waiting for a manual
            # /admin/rag/reindex that is easy to forget. The comparison uses
            # local files only; embeddings are spent solely on real drift.
            try:
                chunks = build_corpus(resume_path, projects_dir)
                current = {(c.title, c.text) for c in chunks if c.text and c.text.strip()}
                stored = {
                    (str(p.get("title", "")), str(p.get("text", "")))
                    for p in pipeline._keyword_documents
                }
                if stored != current:
                    logger.info(
                        "Indexed content differs from current corpus "
                        f"({len(stored)} stored vs {len(current)} current chunks); auto-reindexing"
                    )
                    pipeline.reindex(resume_path, projects_dir)
                else:
                    logger.info(
                        f"Collection already indexed with {points_count} points, matches current corpus"
                    )
            except Exception:
                logger.warning(
                    "Corpus drift check failed; keeping existing index", exc_info=True
                )
            return pipeline

    # Collection is empty or doesn't exist - index it
    logger.info("Indexing resume data...")
    chunks = build_corpus(resume_path, projects_dir)
    pipeline.index_chunks(chunks)
    logger.info(f"✅ Indexed {len(chunks)} chunks successfully")

    return pipeline

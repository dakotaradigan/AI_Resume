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
import threading
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

_TOKEN_RE = re.compile(r"[a-z0-9+#]+(?:\.[a-z0-9+#]+)*")
_RRF_K = 60
_VECTOR_SIZE = 1536
_VECTOR_DISTANCE = "cosine"
_INDEX_SCHEMA_VERSION = 1
_BM25_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "at",
        "be",
        "been",
        "did",
        "do",
        "does",
        "for",
        "he",
        "her",
        "his",
        "how",
        "in",
        "is",
        "it",
        "me",
        "of",
        "on",
        "or",
        "tell",
        "that",
        "the",
        "their",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "would",
        "with",
        "you",
        "your",
        "yours",
        "can",
        "could",
        "should",
        "i",
        "we",
        "they",
        "them",
        "this",
        "these",
        "those",
        "from",
        "by",
        "as",
        "if",
        "then",
        "than",
        "not",
        "no",
        "has",
        "have",
        "had",
        "am",
        "being",
        "please",
        "more",
        "s",
        "t",
    }
)


@dataclass
class DocumentChunk:
    """Represents a chunk of resume or project source data with metadata."""

    text: str
    chunk_type: str  # e.g. personal, experience, project, project_doc, skills
    title: str
    timeframe: str | None = None
    tags: list[str] | None = None


@dataclass(frozen=True)
class _KeywordIndexState:
    """One immutable generation of the in-process BM25 index."""

    documents: tuple[dict[str, Any], ...]
    term_frequencies: tuple[Counter[str], ...]
    document_frequencies: Counter[str]
    average_document_length: float


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
        # Search and the live Qdrant/BM25 generation switch must be one
        # process-local state transition. Searches compare this version after
        # the network call so concurrent requests do not serialize, while any
        # request overlapping reindex is discarded instead of mixing indexes.
        self._generation_lock = threading.RLock()
        self._generation_version = 0
        self._keyword_index = _KeywordIndexState((), (), Counter(), 0.0)
        self._corpus_current = False
        self._dense_retrieval_status = "not_tested"

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
                vectors_config=VectorParams(size=_VECTOR_SIZE, distance=Distance.COSINE),
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
    def _validate_collection_schema(collection_info: Any) -> None:
        """Fail closed unless Qdrant uses the embedding model's actual schema."""
        try:
            vectors_config = collection_info.config.params.vectors
        except AttributeError as exc:
            raise RuntimeError(
                "Could not verify the Qdrant collection vector configuration."
            ) from exc

        vector_size = getattr(vectors_config, "size", None)
        distance = getattr(vectors_config, "distance", None)
        distance_value = str(getattr(distance, "value", distance)).lower()
        if vector_size != _VECTOR_SIZE or distance_value != _VECTOR_DISTANCE:
            raise RuntimeError(
                "Qdrant collection schema mismatch: expected one unnamed "
                f"{_VECTOR_SIZE}-dimensional {_VECTOR_DISTANCE} vector. "
                "Refusing to overwrite or delete the existing collection; "
                "migrate it explicitly."
            )

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

    def _prepare_points(
        self, chunks: list[DocumentChunk]
    ) -> tuple[list[PointStruct], list[dict[str, Any]]]:
        """Build all embeddings and payloads before mutating Qdrant."""
        # Filter empty chunks to avoid wasting embedding API calls
        valid_chunks = [c for c in chunks if c.text and c.text.strip()]
        if len(valid_chunks) < len(chunks):
            logger.warning(
                f"Filtered {len(chunks) - len(valid_chunks)} empty chunks "
                f"(processing {len(valid_chunks)} valid chunks)"
            )
        if not valid_chunks:
            raise ValueError("Cannot index an empty RAG corpus.")

        points: list[PointStruct] = []
        payloads: list[dict[str, Any]] = []
        for idx, chunk in enumerate(valid_chunks):
            embedding = self.embed_text(chunk.text)
            if len(embedding) != _VECTOR_SIZE:
                raise ValueError(
                    f"Embedding for {chunk.title!r} has {len(embedding)} dimensions; "
                    f"expected {_VECTOR_SIZE}."
                )

            payload = self._chunk_payload(chunk)
            point = PointStruct(
                id=idx,
                vector=embedding,
                payload=payload,
            )
            points.append(point)
            payloads.append(payload)

        return points, payloads

    def _chunk_payload(self, chunk: DocumentChunk) -> dict[str, Any]:
        return {
            "text": chunk.text,
            "type": chunk.chunk_type,
            "title": chunk.title,
            "timeframe": chunk.timeframe or "",
            "tags": chunk.tags or [],
            "embedding_model": self.embedding_model,
            "vector_size": _VECTOR_SIZE,
            "vector_distance": _VECTOR_DISTANCE,
            "index_schema_version": _INDEX_SCHEMA_VERSION,
        }

    def index_chunks(self, chunks: list[DocumentChunk]) -> None:
        """Index chunks into Qdrant with embeddings."""
        points, payloads = self._prepare_points(chunks)
        with self._generation_lock:
            self._corpus_current = False
            self._dense_retrieval_status = "not_tested"
            self.qdrant_client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True,
            )
            self._build_keyword_index(payloads)
            self._generation_version += 1
            self._corpus_current = True
        logger.info(f"Indexed {len(points)} chunks into Qdrant")

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return _TOKEN_RE.findall(text.lower())

    @property
    def keyword_documents_count(self) -> int:
        return len(self._keyword_index.documents)

    @property
    def keyword_index_ready(self) -> bool:
        document_count = self.keyword_documents_count
        return (
            document_count > 0
            and len(self._keyword_index.term_frequencies) == document_count
            and self._keyword_index.average_document_length > 0
        )

    @property
    def keyword_documents(self) -> tuple[dict[str, Any], ...]:
        return self._keyword_index.documents

    @property
    def corpus_current(self) -> bool:
        return self._corpus_current

    @property
    def dense_retrieval_status(self) -> str:
        return self._dense_retrieval_status

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
        self._keyword_index = _KeywordIndexState(
            documents=tuple(payloads),
            term_frequencies=tuple(term_frequencies),
            document_frequencies=document_frequencies,
            average_document_length=average_document_length,
        )

    def _scroll_records_from_qdrant(self, *, with_payload: bool) -> list[Any]:
        records: list[Any] = []
        offset: Any = None

        while True:
            page, next_offset = self.qdrant_client.scroll(
                collection_name=self.collection_name,
                limit=100,
                offset=offset,
                with_payload=with_payload,
                with_vectors=False,
            )
            records.extend(page)
            if next_offset is None:
                return records
            offset = next_offset

    def _scroll_payloads_from_qdrant(self) -> list[dict[str, Any]]:
        return [
            dict(record.payload)
            for record in self._scroll_records_from_qdrant(with_payload=True)
            if record.payload
        ]

    def _scroll_point_ids_from_qdrant(self) -> list[int | str]:
        return [
            record.id
            for record in self._scroll_records_from_qdrant(with_payload=False)
        ]

    def _rebuild_keyword_index_from_qdrant(self) -> None:
        """Restore the BM25 index from all stored payloads without re-embedding."""
        payloads = self._scroll_payloads_from_qdrant()
        self._build_keyword_index(payloads)
        logger.info(f"Rebuilt keyword index from {len(payloads)} stored chunks")

    def _bm25_rank(
        self,
        query: str,
        keyword_index: _KeywordIndexState | None = None,
    ) -> list[tuple[int, float]]:
        """Return positive-score document indexes ranked by BM25."""
        keyword_index = keyword_index or self._keyword_index
        query_tokens = list(
            dict.fromkeys(
                token
                for token in self._tokenize(query)
                if token not in _BM25_STOP_WORDS
            )
        )
        document_count = len(keyword_index.documents)
        if (
            not query_tokens
            or not document_count
            or keyword_index.average_document_length == 0
        ):
            return []

        scores = [0.0] * document_count
        for term in query_tokens:
            document_frequency = keyword_index.document_frequencies.get(term, 0)
            if document_frequency == 0:
                continue
            inverse_document_frequency = math.log(
                1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            for index, frequencies in enumerate(keyword_index.term_frequencies):
                term_frequency = frequencies.get(term, 0)
                if term_frequency == 0:
                    continue
                document_length = sum(frequencies.values())
                length_normalization = 1 - 0.75 + (
                    0.75 * document_length / keyword_index.average_document_length
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
        with self._generation_lock:
            if not self._corpus_current:
                return []
            keyword_index = self._keyword_index
            generation_version = self._generation_version

        results, dense_status = self._search_current_generation(
            query,
            limit,
            score_threshold,
            keyword_index,
        )
        with self._generation_lock:
            if (
                not self._corpus_current
                or generation_version != self._generation_version
            ):
                return []
            self._dense_retrieval_status = dense_status
            return results

    def _search_current_generation(
        self,
        query: str,
        limit: int,
        score_threshold: float,
        keyword_index: _KeywordIndexState,
    ) -> tuple[list[dict[str, Any]], str]:
        """Search one immutable keyword generation and report dense health."""
        keyword_ranking = self._bm25_rank(query, keyword_index)
        vector_results: dict[tuple[str, str, str], dict[str, Any]] = {}
        fused_scores: dict[tuple[str, str, str], float] = {}
        try:
            query_embedding = self.embed_text(query)
            response = self.qdrant_client.query_points(
                collection_name=self.collection_name,
                query=query_embedding,
                limit=limit,
                score_threshold=score_threshold,
            )
            for rank, result in enumerate(response.points, 1):
                payload = dict(result.payload or {})
                key = self._payload_key(payload)
                vector_results[key] = payload | {"score": float(result.score)}
                fused_scores[key] = fused_scores.get(key, 0.0) + 1 / (_RRF_K + rank)
            dense_status = "healthy"
        except Exception as exc:
            # Exact-keyword retrieval remains useful during an embedding or
            # vector-store outage. The caller still falls back to static context
            # when BM25 has no signal.
            vector_results.clear()
            fused_scores.clear()
            dense_status = "degraded"
            logger.warning(
                "Dense retrieval failed (%s); continuing with BM25-only results",
                type(exc).__name__,
            )

        keyword_ranks: dict[tuple[str, str, str], int] = {}
        keyword_results: dict[tuple[str, str, str], dict[str, Any]] = {}
        for rank, (index, _) in enumerate(keyword_ranking, 1):
            payload = keyword_index.documents[index]
            key = self._payload_key(payload)
            keyword_ranks[key] = rank
            keyword_results[key] = payload
            fused_scores[key] = fused_scores.get(key, 0.0) + 1 / (_RRF_K + rank)

        if not vector_results and not keyword_ranking:
            return [], dense_status

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
        return formatted_results, dense_status

    @staticmethod
    def _payload_key(payload: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(payload.get("title", "")),
            str(payload.get("type", "")),
            str(payload.get("text", "")),
        )

    @staticmethod
    def _payload_signature(payload: dict[str, Any]) -> tuple[Any, ...]:
        raw_tags = payload.get("tags", [])
        tags = raw_tags if isinstance(raw_tags, list) else [raw_tags]
        return (
            str(payload.get("title", "")),
            str(payload.get("text", "")),
            str(payload.get("type", "")),
            str(payload.get("timeframe", "")),
            tuple(sorted(str(tag) for tag in tags)),
            str(payload.get("embedding_model", "")),
            payload.get("vector_size"),
            str(payload.get("vector_distance", "")),
            payload.get("index_schema_version"),
        )

    def reindex(
        self, resume_path: Path, projects_dir: Path | None = None
    ) -> dict[str, Any]:
        """
        Force re-indexing of resume data.

        Prepare every embedding, update points in place, remove stale point IDs,
        verify the stored generation, then atomically publish the BM25 snapshot.

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
        chunks = build_corpus(resume_path, projects_dir)
        candidate_payloads = [
            self._chunk_payload(chunk)
            for chunk in chunks
            if chunk.text and chunk.text.strip()
        ]
        current_signatures = Counter(
            self._payload_signature(payload) for payload in self.keyword_documents
        )
        candidate_signatures = Counter(
            self._payload_signature(payload) for payload in candidate_payloads
        )
        if candidate_signatures != current_signatures:
            # Source drift is already known even though Qdrant has not changed.
            # Fail closed while embeddings are prepared.
            with self._generation_lock:
                self._corpus_current = False
        points, payloads = self._prepare_points(chunks)

        old_point_ids: list[int | str]
        try:
            old_point_ids = self._scroll_point_ids_from_qdrant()
        except Exception as exc:
            exc_str = str(exc).lower()
            if "not found" in exc_str or "doesn't exist" in exc_str or "404" in exc_str:
                logger.info("Collection doesn't exist yet, will create fresh")
                self._initialize_collection()
                old_point_ids = []
            else:
                raise RuntimeError(
                    f"Could not inspect collection {self.collection_name}: {exc}"
                ) from exc

        old_points_count = len(old_point_ids)
        with self._generation_lock:
            self._corpus_current = False
            self._dense_retrieval_status = "not_tested"

        self.qdrant_client.upsert(
            collection_name=self.collection_name,
            points=points,
            wait=True,
        )
        new_point_ids = set(range(len(points)))
        stale_point_ids = [
            point_id for point_id in old_point_ids if point_id not in new_point_ids
        ]
        if stale_point_ids:
            self.qdrant_client.delete(
                collection_name=self.collection_name,
                points_selector=stale_point_ids,
                wait=True,
            )

        count_result = self.qdrant_client.count(
            collection_name=self.collection_name,
            exact=True,
        )
        stored_count = int(getattr(count_result, "count", 0) or 0)
        if stored_count != len(points):
            raise RuntimeError(
                f"Reindex verification failed: expected {len(points)} points, "
                f"found {stored_count}."
            )

        stored_payloads = self._scroll_payloads_from_qdrant()
        expected_signatures = Counter(
            self._payload_signature(payload) for payload in payloads
        )
        stored_signatures = Counter(
            self._payload_signature(payload) for payload in stored_payloads
        )
        if stored_signatures != expected_signatures:
            raise RuntimeError(
                "Reindex verification failed: stored payloads do not match corpus."
            )

        with self._generation_lock:
            self._build_keyword_index(payloads)
            self._generation_version += 1
            self._corpus_current = True
            self._dense_retrieval_status = "not_tested"

        new_points_count = len(points)
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
    collection_name: str = "resume",
) -> RAGPipeline:
    """
    Initialize and index the RAG pipeline.

    Args:
        openai_api_key: OpenAI API key
        resume_path: Path to resume.json
        qdrant_url: Qdrant URL (required)
        qdrant_api_key: Qdrant API key (used for Qdrant Cloud)
        projects_dir: Optional directory containing project markdown files
        collection_name: Qdrant collection to initialize

    Returns:
        Initialized RAGPipeline
    """
    # Initialize pipeline
    pipeline = RAGPipeline(
        openai_api_key=openai_api_key,
        qdrant_url=qdrant_url,
        qdrant_api_key=qdrant_api_key,
        collection_name=collection_name,
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
            raise RuntimeError(
                f"Could not inspect collection {pipeline.collection_name}: {exc}"
            ) from exc
    else:
        pipeline._validate_collection_schema(collection_info)
        if points_count > 0:
            pipeline._rebuild_keyword_index_from_qdrant()
            # Self-healing index: when the stored chunks differ from what the
            # current data files produce (resume.json edited, project docs
            # added), rebuild automatically instead of waiting for a manual
            # /admin/rag/reindex that is easy to forget. The comparison uses
            # local files only; embeddings are spent solely on real drift.
            try:
                chunks = build_corpus(resume_path, projects_dir)
                current_payloads = [
                    pipeline._chunk_payload(chunk)
                    for chunk in chunks
                    if chunk.text and chunk.text.strip()
                ]
                current = Counter(
                    pipeline._payload_signature(payload) for payload in current_payloads
                )
                stored = Counter(
                    pipeline._payload_signature(payload)
                    for payload in pipeline.keyword_documents
                )
                if stored != current:
                    pipeline._corpus_current = False
                    logger.info(
                        "Indexed content differs from current corpus "
                        f"({sum(stored.values())} stored vs "
                        f"{sum(current.values())} current chunks); auto-reindexing"
                    )
                    pipeline.reindex(resume_path, projects_dir)
                else:
                    pipeline._corpus_current = True
                    logger.info(
                        f"Collection already indexed with {points_count} points, matches current corpus"
                    )
            except Exception:
                pipeline._corpus_current = False
                logger.warning(
                    "Corpus validation or reindex failed; marking index degraded",
                    exc_info=True,
                )
            return pipeline

    # Collection is empty or doesn't exist - index it
    logger.info("Indexing resume data...")
    chunks = build_corpus(resume_path, projects_dir)
    pipeline.index_chunks(chunks)
    logger.info(f"✅ Indexed {len(chunks)} chunks successfully")

    return pipeline

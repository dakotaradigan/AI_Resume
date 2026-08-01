"""RAGPipeline: embedding, Qdrant indexing, and hybrid retrieval.

Dense (OpenAI embeddings + Qdrant) and lexical (BM25) rankings are fused with
reciprocal rank fusion. Reindexing prepares every embedding before touching the
live collection and never deletes it.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import Counter
from pathlib import Path
from typing import Any

from openai import OpenAI, OpenAIError
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from rag.chunking import DocumentChunk, build_corpus, chunk_resume_data
from rag.keyword_index import (
    EMPTY_INDEX,
    KeywordIndexState,
    bm25_rank,
    build_keyword_index,
    tokenize,
)

logger = logging.getLogger(__name__)

_RRF_K = 60
_VECTOR_SIZE = 1536
_VECTOR_DISTANCE = "cosine"
_INDEX_SCHEMA_VERSION = 1


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
        self._keyword_index = EMPTY_INDEX
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
        """Chunk resume JSON into semantic units (see ``rag.chunking``)."""
        return chunk_resume_data(resume_path)

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
        return tokenize(text)

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
        """Publish a fresh BM25 index generation from Qdrant-compatible payloads."""
        self._keyword_index = build_keyword_index(payloads)

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
        keyword_index: KeywordIndexState | None = None,
    ) -> list[tuple[int, float]]:
        """Return positive-score document indexes ranked by BM25."""
        return bm25_rank(query, keyword_index or self._keyword_index)

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
        keyword_index: KeywordIndexState,
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

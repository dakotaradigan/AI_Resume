"""
Unit tests for the RAG pipeline.

Unit tests are fully offline. The opt-in integration test requires Qdrant but
does not require an OpenAI API key because embeddings are mocked.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from rag import (
    RAGPipeline,
    build_corpus,
    chunk_project_docs,
    initialize_rag_pipeline,
)


BASE_DIR = Path(__file__).resolve().parent.parent
RESUME_PATH = BASE_DIR / "data" / "resume.json"


def _zero_embedding(_: str) -> list[float]:
    # Must match the collection vector size (1536 for text-embedding-3-small).
    return [0.0] * 1536


def _offline_pipeline(payloads: list[dict] | None = None) -> RAGPipeline:
    pipeline = object.__new__(RAGPipeline)
    pipeline.collection_name = "resume"
    pipeline.qdrant_client = MagicMock()
    pipeline._build_keyword_index(payloads or [])
    pipeline.embed_text = MagicMock(return_value=_zero_embedding(""))
    return pipeline


class TestProjectDocumentChunking(unittest.TestCase):
    def test_chunks_h2_sections_and_merges_short_sections(self) -> None:
        markdown = """# Example Project

## Overview
This opening section is intentionally longer than three hundred characters. """ + (
            "Architecture details and product context. " * 8
        ) + """

## Tiny Note
Short supporting detail.

## Results
This results section is also intentionally longer than three hundred characters. """ + (
            "Measured impact and implementation evidence. " * 8
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            projects_dir = Path(temp_dir)
            (projects_dir / "example.md").write_text(markdown, encoding="utf-8")

            chunks = chunk_project_docs(projects_dir)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].title, "Example Project — Overview")
        self.assertEqual(chunks[0].chunk_type, "project_doc")
        self.assertIn("## Tiny Note", chunks[0].text)
        self.assertEqual(chunks[1].title, "Example Project — Results")

    def test_build_corpus_gracefully_handles_missing_projects_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            resume_path = Path(temp_dir) / "resume.json"
            resume_path.write_text("{}", encoding="utf-8")

            chunks = build_corpus(resume_path, Path(temp_dir) / "missing")

        self.assertEqual(chunks, [])


class TestHybridRetrieval(unittest.TestCase):
    def test_bm25_ranks_exact_term_match_first(self) -> None:
        pipeline = _offline_pipeline(
            [
                {"title": "General", "type": "project", "text": "AI assistant platform"},
                {
                    "title": "Pinecone Project",
                    "type": "project_doc",
                    "text": "Pinecone vector database benchmark retrieval",
                },
                {"title": "Other", "type": "skills", "text": "Python FastAPI"},
            ]
        )

        ranking = pipeline._bm25_rank("Which project used Pinecone?")

        self.assertEqual(ranking[0][0], 1)
        self.assertGreater(ranking[0][1], 0)

    def test_rrf_fusion_is_deterministic(self) -> None:
        payloads = [
            {"title": "Vector Only", "type": "project", "text": "semantic search"},
            {"title": "Keyword Only", "type": "project", "text": "qdrant retrieval"},
            {"title": "Both", "type": "project", "text": "qdrant architecture"},
        ]
        pipeline = _offline_pipeline(payloads)
        pipeline.qdrant_client.query_points.return_value = SimpleNamespace(
            points=[
                SimpleNamespace(payload=payloads[0], score=0.9),
                SimpleNamespace(payload=payloads[2], score=0.8),
            ]
        )

        first = pipeline.search("qdrant", limit=3, score_threshold=0.30)
        second = pipeline.search("qdrant", limit=3, score_threshold=0.30)

        self.assertEqual(first, second)
        self.assertEqual(first[0]["title"], "Both")
        self.assertEqual(first[0]["score"], 0.8)
        self.assertEqual(first[0]["keyword_rank"], 2)
        self.assertEqual(first[1]["score"], 0.0)

    def test_returns_empty_when_vector_and_bm25_have_no_signal(self) -> None:
        pipeline = _offline_pipeline(
            [{"title": "Python", "type": "skills", "text": "Python FastAPI"}]
        )
        pipeline.qdrant_client.query_points.return_value = SimpleNamespace(points=[])

        self.assertEqual(pipeline.search("watercolor"), [])

    def test_cold_start_scroll_rebuild_paginates(self) -> None:
        payloads = [
            {"title": "One", "type": "project", "text": "first page"},
            {"title": "Two", "type": "project", "text": "second page"},
        ]
        pipeline = _offline_pipeline()
        pipeline.qdrant_client.scroll.side_effect = [
            ([SimpleNamespace(payload=payloads[0])], 42),
            ([SimpleNamespace(payload=payloads[1])], None),
        ]

        pipeline._rebuild_keyword_index_from_qdrant()

        self.assertEqual(pipeline._keyword_documents, payloads)
        self.assertEqual(
            [call.kwargs["offset"] for call in pipeline.qdrant_client.scroll.call_args_list],
            [None, 42],
        )
        pipeline.embed_text.assert_not_called()

    @patch("rag.RAGPipeline")
    def test_initialize_skips_reindex_when_corpus_matches(
        self, pipeline_class: MagicMock
    ) -> None:
        pipeline = _offline_pipeline()
        # build_corpus resolves the patched rag.RAGPipeline; restore the real
        # chunker BEFORE building the corpus so both this test and the drift
        # comparison inside initialize see the actual chunks.
        pipeline_class.chunk_resume_data = RAGPipeline.chunk_resume_data
        current_corpus = build_corpus(RESUME_PATH, BASE_DIR / "data" / "projects")
        pipeline.qdrant_client.get_collection.return_value = SimpleNamespace(
            points_count=len(current_corpus)
        )
        pipeline._rebuild_keyword_index_from_qdrant = MagicMock()
        # Simulate stored payloads identical to what the data files produce.
        pipeline._keyword_documents = [
            {"title": c.title, "text": c.text} for c in current_corpus
        ]
        pipeline.index_chunks = MagicMock()
        pipeline.reindex = MagicMock()
        pipeline_class.return_value = pipeline

        result = initialize_rag_pipeline(
            openai_api_key="test",
            resume_path=RESUME_PATH,
            qdrant_url="https://qdrant.invalid",
            projects_dir=BASE_DIR / "data" / "projects",
        )

        self.assertIs(result, pipeline)
        pipeline._rebuild_keyword_index_from_qdrant.assert_called_once_with()
        pipeline.index_chunks.assert_not_called()
        pipeline.reindex.assert_not_called()

    @patch("rag.RAGPipeline")
    def test_initialize_auto_reindexes_on_corpus_drift(
        self, pipeline_class: MagicMock
    ) -> None:
        pipeline = _offline_pipeline()
        pipeline.qdrant_client.get_collection.return_value = SimpleNamespace(points_count=2)
        pipeline._rebuild_keyword_index_from_qdrant = MagicMock()
        # Stored payloads from an older corpus: content no longer matches.
        pipeline._keyword_documents = [{"title": "Old Chunk", "text": "stale"}]
        pipeline.reindex = MagicMock()
        pipeline_class.return_value = pipeline
        pipeline_class.chunk_resume_data = RAGPipeline.chunk_resume_data

        result = initialize_rag_pipeline(
            openai_api_key="test",
            resume_path=RESUME_PATH,
            qdrant_url="https://qdrant.invalid",
            projects_dir=BASE_DIR / "data" / "projects",
        )

        self.assertIs(result, pipeline)
        pipeline.reindex.assert_called_once_with(
            RESUME_PATH, BASE_DIR / "data" / "projects"
        )


@unittest.skipUnless(
    os.getenv("RUN_INTEGRATION") == "1" and bool(os.getenv("QDRANT_URL")),
    "Integration test disabled. Set RUN_INTEGRATION=1 and QDRANT_URL to enable.",
)
class TestRAGPipelineQdrantIntegration(unittest.TestCase):
    def test_chunk_index_search_with_qdrant(self) -> None:
        qdrant_url = os.getenv("QDRANT_URL", "").strip()
        qdrant_api_key = os.getenv("QDRANT_API_KEY", "").strip()
        self.assertTrue(qdrant_url, "QDRANT_URL must be set for integration tests.")

        # Use an isolated collection so tests never collide with demo data.
        collection_name = f"resume_test_{uuid4().hex}"
        pipeline = RAGPipeline(
            openai_api_key="test",
            qdrant_url=qdrant_url,
            qdrant_api_key=qdrant_api_key,
            collection_name=collection_name,
        )
        try:
            chunks = pipeline.chunk_resume_data(RESUME_PATH)
            self.assertGreater(len(chunks), 0)

            with patch.object(pipeline, "embed_text", side_effect=_zero_embedding):
                pipeline.index_chunks(chunks[:8])  # keep it cheap
                results = pipeline.search("Tell me about Ben AI", limit=2, score_threshold=0.0)

            self.assertGreater(len(results), 0)
            self.assertIn("text", results[0])
            self.assertIn("title", results[0])
            self.assertIn("type", results[0])
            self.assertIn("score", results[0])
        finally:
            # Best-effort cleanup so we don't leave junk in the cluster.
            try:
                pipeline.qdrant_client.delete_collection(collection_name=collection_name)
            except Exception:
                pass


class TestRetrieveRagContext(unittest.TestCase):
    """Unit tests for retrieve_rag_context (no Qdrant needed)."""

    def test_returns_sources_on_success(self) -> None:
        from main import retrieve_rag_context
        from unittest.mock import MagicMock

        mock_pipeline = MagicMock()
        mock_pipeline.search.return_value = [
            {"text": "chunk 1 text", "title": "Ben AI", "type": "project", "score": 0.9, "timeframe": ""},
            {"text": "chunk 2 text", "title": "VP Senior PM", "type": "experience", "score": 0.8, "timeframe": ""},
        ]
        context, used_rag, sources = retrieve_rag_context(mock_pipeline, "AI experience")
        self.assertTrue(used_rag)
        self.assertEqual(
            sources,
            [
                {"title": "Ben AI", "score": 0.9},
                {"title": "VP Senior PM", "score": 0.8},
            ],
        )
        self.assertIn("Ben AI", context)

    def test_returns_empty_on_no_results(self) -> None:
        from main import retrieve_rag_context
        from unittest.mock import MagicMock

        mock_pipeline = MagicMock()
        mock_pipeline.search.return_value = []
        context, used_rag, titles = retrieve_rag_context(mock_pipeline, "something obscure")
        self.assertFalse(used_rag)
        self.assertEqual(titles, [])

    def test_returns_empty_on_none_pipeline(self) -> None:
        from main import retrieve_rag_context
        context, used_rag, titles = retrieve_rag_context(None, "any query")
        self.assertFalse(used_rag)
        self.assertEqual(titles, [])


if __name__ == "__main__":
    unittest.main()

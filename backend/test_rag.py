"""
Unit tests for the RAG pipeline.

Unit tests are fully offline. The opt-in integration test requires Qdrant but
does not require an OpenAI API key because embeddings are mocked.
"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

# Importing main builds the application. Force its supported static mode so this
# module stays offline even when a developer has live credentials in backend/.env.
os.environ["USE_RAG"] = "false"

from evals.scripts.run_retrieval_eval import (
    DEFAULT_EVAL_COLLECTION,
    run_retrieval_eval,
    validate_eval_collection,
)
from rag import (
    DocumentChunk,
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


def _collection_info(
    points_count: int,
    *,
    vector_size: int = 1536,
    distance: str = "Cosine",
) -> SimpleNamespace:
    return SimpleNamespace(
        points_count=points_count,
        config=SimpleNamespace(
            params=SimpleNamespace(
                vectors=SimpleNamespace(size=vector_size, distance=distance)
            )
        ),
    )


def _offline_pipeline(payloads: list[dict] | None = None) -> RAGPipeline:
    pipeline = object.__new__(RAGPipeline)
    pipeline.embedding_model = "text-embedding-3-small"
    pipeline.collection_name = "resume"
    pipeline._generation_lock = threading.RLock()
    pipeline._generation_version = 0
    pipeline.qdrant_client = MagicMock()
    pipeline._build_keyword_index(payloads or [])
    pipeline._corpus_current = True
    pipeline._dense_retrieval_status = "not_tested"
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
    def test_tokenizer_keeps_internal_periods_but_drops_punctuation(self) -> None:
        self.assertEqual(
            RAGPipeline._tokenize("Qdrant. Node.js, C++ and C#."),
            ["qdrant", "node.js", "c++", "and", "c#"],
        )

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

    def test_bm25_matches_word_with_sentence_punctuation(self) -> None:
        pipeline = _offline_pipeline(
            [{"title": "Vector Store", "type": "project", "text": "Uses Qdrant."}]
        )

        ranking = pipeline._bm25_rank("qdrant")

        self.assertEqual(ranking[0][0], 0)
        self.assertGreater(ranking[0][1], 0)

    def test_bm25_does_not_score_stopwords_after_informative_match(self) -> None:
        pipeline = _offline_pipeline(
            [
                {
                    "title": "Generic",
                    "type": "project",
                    "text": "What is the role that he held?",
                },
                {
                    "title": "Personal",
                    "type": "personal",
                    "text": "Dakota is a product leader.",
                },
            ]
        )

        ranking = pipeline._bm25_rank("What is Dakota's background?")

        self.assertEqual([index for index, _ in ranking], [1])

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
        self.assertEqual(pipeline.dense_retrieval_status, "healthy")

    def test_returns_empty_when_vector_and_bm25_have_no_signal(self) -> None:
        pipeline = _offline_pipeline(
            [{"title": "Python", "type": "skills", "text": "Python FastAPI"}]
        )
        pipeline.qdrant_client.query_points.return_value = SimpleNamespace(points=[])

        self.assertEqual(pipeline.search("watercolor"), [])

    def test_embedding_failure_still_returns_bm25_results(self) -> None:
        pipeline = _offline_pipeline(
            [{"title": "Ben AI", "type": "project", "text": "Qdrant retrieval"}]
        )
        pipeline.embed_text.side_effect = RuntimeError("embedding unavailable")

        results = pipeline.search("qdrant")

        self.assertEqual([result["title"] for result in results], ["Ben AI"])
        self.assertEqual(results[0]["score"], 0.0)
        self.assertEqual(pipeline.dense_retrieval_status, "degraded")
        pipeline.qdrant_client.query_points.assert_not_called()

    def test_qdrant_failure_still_returns_bm25_results(self) -> None:
        pipeline = _offline_pipeline(
            [{"title": "Ben AI", "type": "project", "text": "Qdrant retrieval"}]
        )
        pipeline.qdrant_client.query_points.side_effect = RuntimeError(
            "vector store unavailable"
        )

        results = pipeline.search("qdrant")

        self.assertEqual([result["title"] for result in results], ["Ben AI"])
        self.assertEqual(results[0]["score"], 0.0)
        self.assertEqual(pipeline.dense_retrieval_status, "degraded")

    def test_dense_failure_and_no_keyword_signal_returns_empty(self) -> None:
        pipeline = _offline_pipeline(
            [{"title": "Python", "type": "skills", "text": "Python FastAPI"}]
        )
        pipeline.embed_text.side_effect = RuntimeError("embedding unavailable")

        self.assertEqual(pipeline.search("watercolor"), [])

    def test_dense_failure_ignores_common_word_only_bm25_matches(self) -> None:
        pipeline = _offline_pipeline(
            [
                {
                    "title": "Generic",
                    "type": "project",
                    "text": "What is the role that he held?",
                }
            ]
        )
        pipeline.embed_text.side_effect = RuntimeError("embedding unavailable")

        self.assertEqual(pipeline.search("What is the weather?"), [])

    def test_empty_vector_results_ignore_common_word_only_bm25_matches(self) -> None:
        pipeline = _offline_pipeline(
            [
                {
                    "title": "Generic",
                    "type": "project",
                    "text": "What is the role that he held?",
                }
            ]
        )
        pipeline.qdrant_client.query_points.return_value = SimpleNamespace(points=[])

        self.assertEqual(pipeline.search("What's the weather?"), [])

    def test_dense_failure_ignores_contraction_fragments(self) -> None:
        pipeline = _offline_pipeline(
            [{"title": "Generic", "type": "project", "text": "What's his role?"}]
        )
        pipeline.embed_text.side_effect = RuntimeError("embedding unavailable")

        self.assertEqual(pipeline.search("What's the weather?"), [])

    def test_search_uses_one_keyword_index_generation(self) -> None:
        old_payloads = [
            {"title": "Old Match", "type": "project", "text": "qdrant retrieval"},
            {"title": "Old Other", "type": "skills", "text": "python"},
        ]
        pipeline = _offline_pipeline(old_payloads)

        def replace_keyword_index(**_kwargs):
            pipeline._build_keyword_index(
                [
                    {"title": "New Other", "type": "skills", "text": "python"},
                    {"title": "New Match", "type": "project", "text": "qdrant retrieval"},
                ]
            )
            return SimpleNamespace(points=[])

        pipeline.qdrant_client.query_points.side_effect = replace_keyword_index

        results = pipeline.search("qdrant")

        self.assertEqual([result["title"] for result in results], ["Old Match"])

    def test_search_discards_results_from_overlapping_reindex(self) -> None:
        old_payload = {"title": "Old", "type": "project", "text": "qdrant old"}
        pipeline = _offline_pipeline([old_payload])
        chunks = [DocumentChunk(text="qdrant new", chunk_type="project", title="New")]
        expected_payload = pipeline._chunk_payload(chunks[0])
        query_started = threading.Event()
        allow_query = threading.Event()
        failures: list[BaseException] = []
        search_results: list[dict] = []
        query_count = 0

        def scroll(**kwargs):
            if kwargs["with_payload"]:
                return ([SimpleNamespace(id=0, payload=expected_payload)], None)
            return ([SimpleNamespace(id=0)], None)

        def query_points(**_kwargs):
            nonlocal query_count
            query_count += 1
            if query_count == 1:
                query_started.set()
                if not allow_query.wait(2):
                    raise TimeoutError("test did not release search")
            return SimpleNamespace(
                points=[SimpleNamespace(payload=expected_payload, score=0.9)]
            )

        pipeline.qdrant_client.scroll.side_effect = scroll
        pipeline.qdrant_client.count.return_value = SimpleNamespace(count=1)
        pipeline.qdrant_client.query_points.side_effect = query_points

        def run_reindex() -> None:
            try:
                with patch("rag.build_corpus", return_value=chunks):
                    pipeline.reindex(RESUME_PATH)
            except BaseException as exc:  # pragma: no cover - assertion reports it
                failures.append(exc)

        def run_search() -> None:
            try:
                search_results.extend(pipeline.search("qdrant"))
            except BaseException as exc:  # pragma: no cover - assertion reports it
                failures.append(exc)

        search_thread = threading.Thread(target=run_search)
        search_thread.start()
        self.assertTrue(query_started.wait(1))

        reindex_thread = threading.Thread(target=run_reindex)
        reindex_thread.start()
        reindex_thread.join(2)
        self.assertFalse(reindex_thread.is_alive())
        self.assertTrue(pipeline.corpus_current)
        self.assertEqual(pipeline._generation_version, 1)

        allow_query.set()
        search_thread.join(2)

        self.assertFalse(search_thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(search_results, [])
        self.assertEqual(pipeline.dense_retrieval_status, "not_tested")
        self.assertEqual(
            [result["title"] for result in pipeline.search("qdrant")],
            ["New"],
        )
        self.assertEqual(pipeline.dense_retrieval_status, "healthy")

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

        self.assertEqual(list(pipeline.keyword_documents), payloads)
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
        pipeline.qdrant_client.get_collection.return_value = _collection_info(
            len(current_corpus)
        )
        pipeline._rebuild_keyword_index_from_qdrant = MagicMock()
        # Simulate stored payloads identical to what the data files produce.
        pipeline._build_keyword_index(
            [pipeline._chunk_payload(chunk) for chunk in current_corpus]
        )
        pipeline._corpus_current = False
        pipeline.qdrant_client.query_points.return_value = SimpleNamespace(
            points=[
                SimpleNamespace(
                    payload=pipeline.keyword_documents[0],
                    score=0.9,
                )
            ]
        )
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
        self.assertTrue(result.corpus_current)
        self.assertEqual(result.search("Dakota")[0]["title"], "Personal Information")
        pipeline._rebuild_keyword_index_from_qdrant.assert_called_once_with()
        pipeline.index_chunks.assert_not_called()
        pipeline.reindex.assert_not_called()

    @patch("rag.RAGPipeline")
    def test_initialize_auto_reindexes_on_corpus_drift(
        self, pipeline_class: MagicMock
    ) -> None:
        pipeline = _offline_pipeline()
        pipeline.qdrant_client.get_collection.return_value = _collection_info(2)
        pipeline._rebuild_keyword_index_from_qdrant = MagicMock()
        # Stored payloads from an older corpus: content no longer matches.
        pipeline._build_keyword_index([{"title": "Old Chunk", "text": "stale"}])
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

    @patch("rag.RAGPipeline")
    def test_initialize_marks_pipeline_degraded_when_auto_reindex_fails(
        self, pipeline_class: MagicMock
    ) -> None:
        pipeline = _offline_pipeline()
        pipeline.qdrant_client.get_collection.return_value = _collection_info(1)
        pipeline._rebuild_keyword_index_from_qdrant = MagicMock()
        pipeline._build_keyword_index([{"title": "Old Chunk", "text": "stale"}])
        pipeline.reindex = MagicMock()
        pipeline.reindex.side_effect = RuntimeError("verification failed")
        pipeline_class.return_value = pipeline
        pipeline_class.chunk_resume_data = RAGPipeline.chunk_resume_data

        result = initialize_rag_pipeline(
            openai_api_key="test",
            resume_path=RESUME_PATH,
            qdrant_url="https://qdrant.invalid",
            projects_dir=BASE_DIR / "data" / "projects",
        )

        self.assertIs(result, pipeline)
        self.assertFalse(result.corpus_current)
        self.assertEqual(result.search("qdrant"), [])
        pipeline.qdrant_client.query_points.assert_not_called()

    @patch("rag.RAGPipeline")
    def test_initialize_reindexes_on_embedding_model_drift(
        self, pipeline_class: MagicMock
    ) -> None:
        pipeline = _offline_pipeline()
        pipeline_class.chunk_resume_data = RAGPipeline.chunk_resume_data
        current_corpus = build_corpus(RESUME_PATH, BASE_DIR / "data" / "projects")
        stored_payloads = [pipeline._chunk_payload(chunk) for chunk in current_corpus]
        stored_payloads[0] = stored_payloads[0] | {"embedding_model": "old-model"}
        pipeline._build_keyword_index(stored_payloads)
        pipeline.qdrant_client.get_collection.return_value = _collection_info(
            len(stored_payloads)
        )
        pipeline._rebuild_keyword_index_from_qdrant = MagicMock()
        pipeline.reindex = MagicMock()
        pipeline_class.return_value = pipeline

        initialize_rag_pipeline(
            openai_api_key="test",
            resume_path=RESUME_PATH,
            qdrant_url="https://qdrant.invalid",
            projects_dir=BASE_DIR / "data" / "projects",
        )

        pipeline.reindex.assert_called_once_with(
            RESUME_PATH, BASE_DIR / "data" / "projects"
        )

    @patch("rag.RAGPipeline")
    def test_initialize_reindexes_when_duplicate_count_differs(
        self, pipeline_class: MagicMock
    ) -> None:
        pipeline = _offline_pipeline()
        pipeline_class.chunk_resume_data = RAGPipeline.chunk_resume_data
        current_corpus = build_corpus(RESUME_PATH, BASE_DIR / "data" / "projects")
        stored_payloads = [pipeline._chunk_payload(chunk) for chunk in current_corpus]
        stored_payloads.append(dict(stored_payloads[0]))
        pipeline._build_keyword_index(stored_payloads)
        pipeline.qdrant_client.get_collection.return_value = _collection_info(
            len(stored_payloads)
        )
        pipeline._rebuild_keyword_index_from_qdrant = MagicMock()
        pipeline.reindex = MagicMock()
        pipeline_class.return_value = pipeline

        initialize_rag_pipeline(
            openai_api_key="test",
            resume_path=RESUME_PATH,
            qdrant_url="https://qdrant.invalid",
            projects_dir=BASE_DIR / "data" / "projects",
        )

        pipeline.reindex.assert_called_once_with(
            RESUME_PATH, BASE_DIR / "data" / "projects"
        )

    @patch("rag.RAGPipeline")
    def test_initialize_passes_explicit_collection_name(
        self, pipeline_class: MagicMock
    ) -> None:
        pipeline = _offline_pipeline()
        pipeline.collection_name = "resume_eval_retrieval"
        pipeline.qdrant_client.get_collection.return_value = _collection_info(0)
        pipeline.index_chunks = MagicMock()
        pipeline_class.return_value = pipeline
        pipeline_class.chunk_resume_data = RAGPipeline.chunk_resume_data

        initialize_rag_pipeline(
            openai_api_key="test",
            resume_path=RESUME_PATH,
            qdrant_url="https://qdrant.invalid",
            projects_dir=BASE_DIR / "data" / "projects",
            collection_name="resume_eval_retrieval",
        )

        self.assertEqual(
            pipeline_class.call_args.kwargs["collection_name"],
            "resume_eval_retrieval",
        )

    @patch("rag.RAGPipeline")
    def test_initialize_aborts_on_unexpected_collection_status_error(
        self, pipeline_class: MagicMock
    ) -> None:
        pipeline = _offline_pipeline()
        pipeline.qdrant_client.get_collection.side_effect = RuntimeError("qdrant unavailable")
        pipeline.index_chunks = MagicMock()
        pipeline_class.return_value = pipeline

        with self.assertRaisesRegex(RuntimeError, "Could not inspect collection"):
            initialize_rag_pipeline(
                openai_api_key="test",
                resume_path=RESUME_PATH,
                qdrant_url="https://qdrant.invalid",
            )

        pipeline.index_chunks.assert_not_called()

    @patch("rag.RAGPipeline")
    def test_initialize_refuses_wrong_collection_distance(
        self, pipeline_class: MagicMock
    ) -> None:
        pipeline = _offline_pipeline()
        pipeline.qdrant_client.get_collection.return_value = _collection_info(
            2,
            distance="Dot",
        )
        pipeline.index_chunks = MagicMock()
        pipeline.reindex = MagicMock()
        pipeline_class.return_value = pipeline

        with self.assertRaisesRegex(RuntimeError, "schema mismatch"):
            initialize_rag_pipeline(
                openai_api_key="test",
                resume_path=RESUME_PATH,
                qdrant_url="https://qdrant.invalid",
            )

        pipeline.index_chunks.assert_not_called()
        pipeline.reindex.assert_not_called()
        pipeline.qdrant_client.upsert.assert_not_called()


class TestIndexingSafety(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks = [
            DocumentChunk(text="first", chunk_type="project", title="First"),
            DocumentChunk(text="second", chunk_type="project", title="Second"),
        ]

    def test_index_chunks_publishes_ready_generation(self) -> None:
        pipeline = _offline_pipeline()
        pipeline._corpus_current = False

        pipeline.index_chunks(self.chunks)

        self.assertTrue(pipeline.corpus_current)
        self.assertTrue(pipeline.keyword_index_ready)
        self.assertEqual(pipeline.keyword_documents_count, 2)
        self.assertEqual(pipeline._generation_version, 1)
        self.assertEqual(pipeline.dense_retrieval_status, "not_tested")
        self.assertTrue(pipeline.qdrant_client.upsert.call_args.kwargs["wait"])

    def test_embedding_failure_leaves_collection_untouched(self) -> None:
        pipeline = _offline_pipeline(
            [{"title": "Old", "type": "project", "text": "old text"}]
        )
        old_keyword_documents = list(pipeline.keyword_documents)
        pipeline.embed_text.side_effect = [_zero_embedding(""), RuntimeError("failed")]

        with patch("rag.build_corpus", return_value=self.chunks):
            with self.assertRaisesRegex(RuntimeError, "failed"):
                pipeline.reindex(RESUME_PATH)

        pipeline.qdrant_client.get_collection.assert_not_called()
        pipeline.qdrant_client.delete_collection.assert_not_called()
        pipeline.qdrant_client.upsert.assert_not_called()
        self.assertEqual(list(pipeline.keyword_documents), old_keyword_documents)
        self.assertFalse(pipeline.corpus_current)

    def test_empty_corpus_leaves_collection_untouched(self) -> None:
        pipeline = _offline_pipeline()

        with patch("rag.build_corpus", return_value=[]):
            with self.assertRaisesRegex(ValueError, "empty RAG corpus"):
                pipeline.reindex(RESUME_PATH)

        pipeline.qdrant_client.delete_collection.assert_not_called()
        pipeline.qdrant_client.upsert.assert_not_called()

    def test_invalid_embedding_dimensions_leave_collection_untouched(self) -> None:
        pipeline = _offline_pipeline()
        pipeline.embed_text.return_value = [0.0]

        with patch("rag.build_corpus", return_value=self.chunks):
            with self.assertRaisesRegex(ValueError, "expected 1536"):
                pipeline.reindex(RESUME_PATH)

        pipeline.qdrant_client.get_collection.assert_not_called()
        pipeline.qdrant_client.delete_collection.assert_not_called()
        pipeline.qdrant_client.upsert.assert_not_called()

    def test_reindex_updates_in_place_after_preparing_and_verifies(self) -> None:
        pipeline = _offline_pipeline()
        events: list[str] = []
        expected_payloads = [pipeline._chunk_payload(chunk) for chunk in self.chunks]
        pipeline.embed_text.side_effect = lambda _: events.append("embed") or _zero_embedding("")

        def scroll(**kwargs):
            if kwargs["with_payload"]:
                events.append("verify")
                return (
                    [
                        SimpleNamespace(id=index, payload=payload)
                        for index, payload in enumerate(expected_payloads)
                    ],
                    None,
                )
            events.append("inspect")
            return ([SimpleNamespace(id=0), SimpleNamespace(id=9)], None)

        pipeline.qdrant_client.scroll.side_effect = scroll
        pipeline.qdrant_client.upsert.side_effect = lambda **_: events.append("upsert")
        pipeline.qdrant_client.delete.side_effect = lambda **_: events.append("delete_stale")
        pipeline.qdrant_client.count.side_effect = (
            lambda **_: events.append("count") or SimpleNamespace(count=2)
        )
        pipeline._initialize_collection = MagicMock()

        with patch("rag.build_corpus", return_value=self.chunks):
            result = pipeline.reindex(RESUME_PATH)

        self.assertEqual(
            events,
            ["embed", "embed", "inspect", "upsert", "delete_stale", "count", "verify"],
        )
        self.assertEqual(result["new_points_count"], 2)
        self.assertEqual(pipeline.keyword_documents_count, 2)
        self.assertTrue(pipeline.corpus_current)
        pipeline.qdrant_client.delete_collection.assert_not_called()
        pipeline._initialize_collection.assert_not_called()
        self.assertEqual(
            pipeline.qdrant_client.delete.call_args.kwargs["points_selector"],
            [9],
        )

    def test_reindex_creates_missing_collection_then_verifies(self) -> None:
        pipeline = _offline_pipeline()
        expected_payloads = [pipeline._chunk_payload(chunk) for chunk in self.chunks]
        missing_reported = False

        def scroll(**kwargs):
            nonlocal missing_reported
            if not kwargs["with_payload"] and not missing_reported:
                missing_reported = True
                raise RuntimeError("404 collection not found")
            return (
                [
                    SimpleNamespace(id=index, payload=payload)
                    for index, payload in enumerate(expected_payloads)
                ],
                None,
            )

        pipeline.qdrant_client.scroll.side_effect = scroll
        pipeline.qdrant_client.count.return_value = SimpleNamespace(count=2)
        pipeline._initialize_collection = MagicMock()

        with patch("rag.build_corpus", return_value=self.chunks):
            result = pipeline.reindex(RESUME_PATH)

        self.assertEqual(result["old_points_count"], 0)
        pipeline._initialize_collection.assert_called_once_with()
        pipeline.qdrant_client.upsert.assert_called_once()
        pipeline.qdrant_client.delete.assert_not_called()
        self.assertTrue(pipeline.corpus_current)

    def test_upsert_failure_keeps_previous_keyword_index(self) -> None:
        pipeline = _offline_pipeline(
            [{"title": "Old", "type": "project", "text": "old text"}]
        )
        old_keyword_documents = list(pipeline.keyword_documents)
        pipeline.qdrant_client.scroll.return_value = ([SimpleNamespace(id=0)], None)
        pipeline.qdrant_client.upsert.side_effect = RuntimeError("upsert failed")

        with patch("rag.build_corpus", return_value=self.chunks):
            with self.assertRaisesRegex(RuntimeError, "upsert failed"):
                pipeline.reindex(RESUME_PATH)

        self.assertEqual(list(pipeline.keyword_documents), old_keyword_documents)
        self.assertFalse(pipeline.corpus_current)
        pipeline.qdrant_client.delete_collection.assert_not_called()
        pipeline.qdrant_client.delete.assert_not_called()

    def test_stale_point_delete_failure_keeps_generation_degraded(self) -> None:
        pipeline = _offline_pipeline(
            [{"title": "Old", "type": "project", "text": "old text"}]
        )
        old_keyword_documents = list(pipeline.keyword_documents)
        pipeline.qdrant_client.scroll.return_value = (
            [SimpleNamespace(id=0), SimpleNamespace(id=9)],
            None,
        )
        pipeline.qdrant_client.delete.side_effect = RuntimeError("delete failed")

        with patch("rag.build_corpus", return_value=self.chunks):
            with self.assertRaisesRegex(RuntimeError, "delete failed"):
                pipeline.reindex(RESUME_PATH)

        self.assertEqual(list(pipeline.keyword_documents), old_keyword_documents)
        self.assertFalse(pipeline.corpus_current)
        pipeline.qdrant_client.count.assert_not_called()

    def test_count_mismatch_keeps_generation_degraded(self) -> None:
        pipeline = _offline_pipeline(
            [{"title": "Old", "type": "project", "text": "old text"}]
        )
        old_keyword_documents = list(pipeline.keyword_documents)
        pipeline.qdrant_client.scroll.return_value = ([SimpleNamespace(id=0)], None)
        pipeline.qdrant_client.count.return_value = SimpleNamespace(count=1)

        with patch("rag.build_corpus", return_value=self.chunks):
            with self.assertRaisesRegex(RuntimeError, "expected 2 points, found 1"):
                pipeline.reindex(RESUME_PATH)

        self.assertEqual(list(pipeline.keyword_documents), old_keyword_documents)
        self.assertFalse(pipeline.corpus_current)

    def test_payload_mismatch_keeps_generation_degraded(self) -> None:
        pipeline = _offline_pipeline(
            [{"title": "Old", "type": "project", "text": "old text"}]
        )
        old_keyword_documents = list(pipeline.keyword_documents)

        def scroll(**kwargs):
            if kwargs["with_payload"]:
                return ([SimpleNamespace(payload={"title": "Wrong"})], None)
            return ([SimpleNamespace(id=0)], None)

        pipeline.qdrant_client.scroll.side_effect = scroll
        pipeline.qdrant_client.count.return_value = SimpleNamespace(count=2)

        with patch("rag.build_corpus", return_value=self.chunks):
            with self.assertRaisesRegex(RuntimeError, "payloads do not match"):
                pipeline.reindex(RESUME_PATH)

        self.assertEqual(list(pipeline.keyword_documents), old_keyword_documents)
        self.assertFalse(pipeline.corpus_current)

    def test_verification_scroll_failure_keeps_generation_degraded(self) -> None:
        pipeline = _offline_pipeline(
            [{"title": "Old", "type": "project", "text": "old text"}]
        )
        old_keyword_documents = list(pipeline.keyword_documents)

        def scroll(**kwargs):
            if kwargs["with_payload"]:
                raise RuntimeError("verification unavailable")
            return ([SimpleNamespace(id=0)], None)

        pipeline.qdrant_client.scroll.side_effect = scroll
        pipeline.qdrant_client.count.return_value = SimpleNamespace(count=2)

        with patch("rag.build_corpus", return_value=self.chunks):
            with self.assertRaisesRegex(RuntimeError, "verification unavailable"):
                pipeline.reindex(RESUME_PATH)

        self.assertEqual(list(pipeline.keyword_documents), old_keyword_documents)
        self.assertFalse(pipeline.corpus_current)

    def test_reindex_aborts_before_write_when_existing_ids_cannot_be_read(self) -> None:
        pipeline = _offline_pipeline(
            [{"title": "Old", "type": "project", "text": "old text"}]
        )
        pipeline.qdrant_client.scroll.side_effect = RuntimeError("qdrant unavailable")

        with patch("rag.build_corpus", return_value=self.chunks):
            with self.assertRaisesRegex(RuntimeError, "Could not inspect collection"):
                pipeline.reindex(RESUME_PATH)

        self.assertFalse(pipeline.corpus_current)
        pipeline.qdrant_client.upsert.assert_not_called()
        pipeline.qdrant_client.delete.assert_not_called()


class TestRetrievalEvalIsolation(unittest.TestCase):
    def test_default_collection_is_isolated(self) -> None:
        self.assertEqual(
            validate_eval_collection(DEFAULT_EVAL_COLLECTION),
            "resume_eval_retrieval",
        )

    def test_production_collection_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "production collection"):
            validate_eval_collection("resume")

    def test_non_eval_collection_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must start"):
            validate_eval_collection("resume_live")

    def test_runner_uses_dedicated_eval_target_and_collection(self) -> None:
        corpus = [DocumentChunk(text="Qdrant", chunk_type="project", title="Only")]
        pipeline = MagicMock()
        pipeline.search.return_value = [{"title": "Only"}]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            dataset_path = temp_path / "golden.jsonl"
            output_path = temp_path / "results.jsonl"
            dataset_path.write_text(
                '{"id":"one","query":"qdrant","expected_titles":["Only"],'
                '"category":"fact"}\n',
                encoding="utf-8",
            )
            settings = SimpleNamespace(
                openai_api_key="openai-test",
                qdrant_url="https://production-qdrant.invalid",
                eval_qdrant_url="https://eval-qdrant.invalid",
                eval_qdrant_api_key="eval-key",
                data_dir=temp_path,
            )
            with (
                redirect_stdout(StringIO()),
                patch(
                    "evals.scripts.run_retrieval_eval.get_settings",
                    return_value=settings,
                ),
                patch(
                    "evals.scripts.run_retrieval_eval.build_corpus",
                    return_value=corpus,
                ),
                patch(
                    "evals.scripts.run_retrieval_eval.initialize_rag_pipeline",
                    return_value=pipeline,
                ) as initialize,
            ):
                run_retrieval_eval(
                    dataset_path,
                    output_path,
                    4,
                    "resume_eval_isolated",
                )

        self.assertEqual(
            initialize.call_args.kwargs["qdrant_url"],
            "https://eval-qdrant.invalid",
        )
        self.assertEqual(initialize.call_args.kwargs["qdrant_api_key"], "eval-key")
        self.assertEqual(
            initialize.call_args.kwargs["collection_name"],
            "resume_eval_isolated",
        )

    def test_runner_rejects_production_collection_before_loading_settings(self) -> None:
        with patch("evals.scripts.run_retrieval_eval.get_settings") as get_settings:
            with self.assertRaisesRegex(ValueError, "production collection"):
                run_retrieval_eval(Path("unused"), Path("unused"), 4, "resume")

        get_settings.assert_not_called()

    def test_runner_rejects_eval_target_matching_production(self) -> None:
        settings = SimpleNamespace(
            openai_api_key="openai-test",
            qdrant_url="https://same-qdrant.invalid/",
            eval_qdrant_url="https://same-qdrant.invalid",
            eval_qdrant_api_key="eval-key",
        )
        with patch(
            "evals.scripts.run_retrieval_eval.get_settings",
            return_value=settings,
        ):
            with self.assertRaisesRegex(RuntimeError, "must differ"):
                run_retrieval_eval(
                    Path("unused"),
                    Path("unused"),
                    4,
                    "resume_eval_isolated",
                )

    def test_runner_never_falls_back_to_production_target(self) -> None:
        settings = SimpleNamespace(
            openai_api_key="openai-test",
            qdrant_url="https://production-qdrant.invalid",
            eval_qdrant_url=None,
            eval_qdrant_api_key="",
        )
        with (
            patch(
                "evals.scripts.run_retrieval_eval.get_settings",
                return_value=settings,
            ),
            patch(
                "evals.scripts.run_retrieval_eval.initialize_rag_pipeline"
            ) as initialize,
        ):
            with self.assertRaisesRegex(RuntimeError, "EVAL_QDRANT_URL is required"):
                run_retrieval_eval(
                    Path("unused"),
                    Path("unused"),
                    4,
                    "resume_eval_isolated",
                )

        initialize.assert_not_called()

    def test_runner_requires_key_for_https_eval_target(self) -> None:
        settings = SimpleNamespace(
            openai_api_key="openai-test",
            qdrant_url="https://production-qdrant.invalid",
            eval_qdrant_url="https://eval-qdrant.invalid",
            eval_qdrant_api_key="",
        )
        with (
            patch(
                "evals.scripts.run_retrieval_eval.get_settings",
                return_value=settings,
            ),
            patch(
                "evals.scripts.run_retrieval_eval.initialize_rag_pipeline"
            ) as initialize,
        ):
            with self.assertRaisesRegex(RuntimeError, "EVAL_QDRANT_API_KEY is required"):
                run_retrieval_eval(
                    Path("unused"),
                    Path("unused"),
                    4,
                    "resume_eval_isolated",
                )

        initialize.assert_not_called()


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

    def test_uses_static_fallback_without_dense_query_when_corpus_is_degraded(self) -> None:
        from main import retrieve_rag_context

        pipeline = _offline_pipeline(
            [{"title": "Old", "type": "project", "text": "qdrant old"}]
        )
        pipeline._corpus_current = False

        context, used_rag, sources = retrieve_rag_context(pipeline, "qdrant")

        self.assertIn("Dakota Radigan", context)
        self.assertFalse(used_rag)
        self.assertEqual(sources, [])
        pipeline.qdrant_client.query_points.assert_not_called()


if __name__ == "__main__":
    unittest.main()

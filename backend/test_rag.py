"""
Unit tests for the RAG pipeline.

These tests are integration-style and require a reachable Qdrant endpoint.

They do NOT require an OpenAI API key because embeddings are mocked.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from rag import RAGPipeline


BASE_DIR = Path(__file__).resolve().parent.parent
RESUME_PATH = BASE_DIR / "data" / "resume.json"


def _zero_embedding(_: str) -> list[float]:
    # Must match the collection vector size (1536 for text-embedding-3-small).
    return [0.0] * 1536


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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from anthropic import AnthropicError, RateLimitError
from fastapi.testclient import TestClient
from starlette.requests import Request


# A recognizable fake secret. If any /api/chat error path ever forwards exception
# text (or the key itself) to the client, this string will show up in the response
# body and the assertions below will fail.
SENTINEL_KEY = "sk-ant-SENTINEL-DO-NOT-LEAK"


class _FakeMessages:
    """Stand-in for client.messages that raises a preset exception on create()."""

    def __init__(self, exc: BaseException):
        self._exc = exc

    async def create(self, **_kwargs):
        raise self._exc


class _FakeAsyncAnthropic:
    """Drop-in for AsyncAnthropic whose messages.create() always raises."""

    def __init__(self, exc: BaseException):
        self.messages = _FakeMessages(exc)


def _fake_client_factory(exc: BaseException):
    """Return a callable matching AsyncAnthropic(...) that yields a raising client."""

    def _factory(**_kwargs):
        return _FakeAsyncAnthropic(exc)

    return _factory


def _rate_limit_error() -> RateLimitError:
    """Build a real RateLimitError whose message embeds the sentinel key.

    Embedding the secret in the exception proves that even a key-bearing upstream
    error does not reach the client, because only HTTPException.detail is serialized.
    """
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, request=request)
    return RateLimitError(
        f"rate limit exceeded for key {SENTINEL_KEY}",
        response=response,
        body=None,
    )


@contextmanager
def configured_app(**env: str):
    base_env = {
        "ADMIN_TOKEN": "",
        "ANTHROPIC_API_KEY": "",
        "OPENAI_API_KEY": "",
        "QDRANT_URL": "",
        "TRUST_PROXY_HEADERS": "",
        "USE_RAG": "false",
    }
    base_env.update(env)

    with patch.dict(os.environ, base_env, clear=False):
        import config

        config.get_settings.cache_clear()
        if "main" in sys.modules:
            main = importlib.reload(sys.modules["main"])
        else:
            import main
        try:
            yield main, main.build_app()
        finally:
            config.get_settings.cache_clear()


def make_request(
    client_host: str = "203.0.113.20",
    forwarded_for: str | None = None,
) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("utf-8")))
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "client": (client_host, 12345),
    })


class TestSecurityHardening(unittest.TestCase):
    def test_trust_proxy_headers_defaults_to_false(self) -> None:
        with configured_app() as (main, _):
            settings = main.get_settings()

        self.assertFalse(settings.trust_proxy_headers)

    def test_trust_proxy_headers_parses_truthy_values(self) -> None:
        with configured_app(TRUST_PROXY_HEADERS="true") as (main, _):
            settings = main.get_settings()

        self.assertTrue(settings.trust_proxy_headers)

    def test_client_ip_ignores_forwarded_for_by_default(self) -> None:
        with configured_app(TRUST_PROXY_HEADERS="false") as (main, _):
            request = make_request(
                client_host="198.51.100.10",
                forwarded_for="192.0.2.1, 192.0.2.2",
            )

            self.assertEqual(
                main._get_client_ip(request, main.get_settings()), "198.51.100.10"
            )

    def test_client_ip_uses_forwarded_for_when_enabled(self) -> None:
        with configured_app(TRUST_PROXY_HEADERS="true") as (main, _):
            request = make_request(
                client_host="198.51.100.10",
                forwarded_for="192.0.2.1, 192.0.2.2",
            )

            # Right-most entry is the one appended by the trusted proxy;
            # left-most entries are client-supplied and spoofable.
            self.assertEqual(
                main._get_client_ip(request, main.get_settings()), "192.0.2.2"
            )

    def test_client_ip_falls_back_when_forwarded_for_is_not_an_ip(self) -> None:
        with configured_app(TRUST_PROXY_HEADERS="true") as (main, _):
            request = make_request(
                client_host="198.51.100.10",
                forwarded_for="spoofed-garbage",
            )

            self.assertEqual(
                main._get_client_ip(request, main.get_settings()), "198.51.100.10"
            )

    def test_compacted_history_uses_supported_roles(self) -> None:
        with configured_app() as (main, _):
            store = main.SessionStore()

            async def scenario() -> list[dict]:
                for i in range(8):
                    await store.append_message("sid", "user", f"question {i}")
                    await store.append_message("sid", "assistant", f"answer {i}")
                await main._compact_session_history("sid", store)
                return await store.get_history("sid")

            history = asyncio.run(scenario())

        self.assertGreater(len(history), 0)
        # The Anthropic Messages API rejects any role besides user/assistant.
        self.assertTrue(
            all(msg["role"] in ("user", "assistant") for msg in history),
            f"Unsupported role in compacted history: {[m['role'] for m in history]}",
        )
        self.assertIn("Earlier conversation summary", history[0]["content"][0]["text"])

    def test_history_compacts_after_seventh_completed_exchange(self) -> None:
        with configured_app() as (main, _):
            store = main.SessionStore()

            async def scenario() -> tuple[list[dict], list[dict]]:
                for i in range(6):
                    await store.append_message("sid", "user", f"question {i}")
                    await store.append_message("sid", "assistant", f"answer {i}")
                await main._compact_session_history("sid", store)
                before_threshold = await store.get_history("sid")
                await store.append_message("sid", "user", "question 6")
                await store.append_message("sid", "assistant", "answer 6")
                await main._compact_session_history("sid", store)
                return before_threshold, await store.get_history("sid")

            before_threshold, compacted = asyncio.run(scenario())

        self.assertEqual(len(before_threshold), 12)
        self.assertEqual(len(compacted), 11)
        self.assertIn("Earlier conversation summary", compacted[0]["content"][0]["text"])
        self.assertEqual(compacted[1:9], before_threshold[4:])
        self.assertEqual(
            [message["content"][0]["text"] for message in compacted[-2:]],
            ["question 6", "answer 6"],
        )

    def test_in_memory_session_expires_after_default_idle_window(self) -> None:
        with configured_app() as (main, _):
            store = main.SessionStore()
            max_age_seconds = main.get_settings().session_max_age_seconds

            async def scenario() -> tuple[int, int, list[dict]]:
                with patch.object(main.time, "time", return_value=100.0):
                    await store.update_metadata("sid")
                    await store.append_message("sid", "user", "remember me")
                with patch.object(main.time, "time", return_value=3700.0):
                    at_boundary = await store.cleanup_expired(max_age_seconds)
                with patch.object(main.time, "time", return_value=3700.1):
                    after_boundary = await store.cleanup_expired(max_age_seconds)
                return at_boundary, after_boundary, await store.get_history("sid")

            at_boundary, after_boundary, history = asyncio.run(scenario())

        self.assertEqual(max_age_seconds, 3600)
        self.assertEqual(at_boundary, 0)
        self.assertEqual(after_boundary, 1)
        self.assertEqual(history, [])

    def test_admin_export_rejects_query_token(self) -> None:
        with configured_app(
            ADMIN_TOKEN="secret",
            ENVIRONMENT="production",
        ) as (_, app):
            response = TestClient(app).get("/admin/analytics/export?token=secret")

        self.assertEqual(response.status_code, 401)

    def test_admin_export_accepts_header_token(self) -> None:
        with configured_app(
            ADMIN_TOKEN="secret",
            ENVIRONMENT="production",
        ) as (_, app):
            response = TestClient(app).get(
                "/admin/analytics/export",
                headers={"X-Admin-Token": "secret"},
            )

        self.assertEqual(response.status_code, 200)

    def test_missing_admin_token_fails_closed_outside_local_dev(self) -> None:
        with configured_app(ADMIN_TOKEN="", ENVIRONMENT="production") as (_, app):
            response = TestClient(app).post("/admin/cache/clear")

        self.assertEqual(response.status_code, 503)

    def test_rag_health_reports_static_fallback_when_uninitialized(self) -> None:
        with configured_app(USE_RAG="false", QDRANT_URL="https://qdrant.example") as (_, app):
            response = TestClient(app).get("/health/rag")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["rag_enabled"])
        self.assertFalse(payload["rag_initialized"])
        self.assertEqual(payload["mode"], "static_fallback")
        self.assertFalse(payload["vector_db_live"])
        self.assertFalse(payload["keyword_index_ready"])
        self.assertFalse(payload["indexes_ready"])
        self.assertEqual(payload["dense_retrieval_status"], "not_initialized")
        self.assertFalse(payload["retrieval_ready"])
        self.assertNotIn("qdrant.example", str(payload))

    def test_rag_health_checks_collection_without_exposing_url(self) -> None:
        class FakeQdrantClient:
            def collection_exists(self, collection_name: str) -> bool:
                return collection_name == "resume"

            def count(self, collection_name: str, exact: bool) -> SimpleNamespace:
                return SimpleNamespace(count=7)

        with configured_app(USE_RAG="true", QDRANT_URL="https://qdrant.example") as (_, app):
            app.state.rag_pipeline = SimpleNamespace(
                collection_name="resume",
                qdrant_client=FakeQdrantClient(),
                keyword_documents_count=7,
                keyword_index_ready=True,
                corpus_current=True,
                dense_retrieval_status="healthy",
            )
            response = TestClient(app).get("/health/rag")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["rag_enabled"])
        self.assertTrue(payload["rag_initialized"])
        self.assertEqual(payload["mode"], "rag")
        self.assertTrue(payload["collection_exists"])
        self.assertEqual(payload["points_count"], 7)
        self.assertTrue(payload["vector_db_live"])
        self.assertEqual(payload["keyword_documents_count"], 7)
        self.assertTrue(payload["keyword_index_ready"])
        self.assertTrue(payload["corpus_current"])
        self.assertTrue(payload["indexes_ready"])
        self.assertEqual(payload["dense_retrieval_status"], "healthy")
        self.assertTrue(payload["retrieval_ready"])
        self.assertNotIn("qdrant.example", str(payload))

    def test_rag_health_reports_count_mismatch_as_not_ready(self) -> None:
        class FakeQdrantClient:
            def collection_exists(self, collection_name: str) -> bool:
                return True

            def count(self, collection_name: str, exact: bool) -> SimpleNamespace:
                return SimpleNamespace(count=7)

        with configured_app(USE_RAG="true", QDRANT_URL="https://qdrant.example") as (_, app):
            app.state.rag_pipeline = SimpleNamespace(
                collection_name="resume",
                qdrant_client=FakeQdrantClient(),
                keyword_documents_count=6,
                keyword_index_ready=True,
                corpus_current=True,
                dense_retrieval_status="healthy",
            )
            response = TestClient(app).get("/health/rag")

        payload = response.json()
        self.assertTrue(payload["vector_db_live"])
        self.assertFalse(payload["indexes_ready"])
        self.assertFalse(payload["retrieval_ready"])

    def test_rag_health_reports_last_dense_failure_as_degraded(self) -> None:
        class FakeQdrantClient:
            def collection_exists(self, collection_name: str) -> bool:
                return True

            def count(self, collection_name: str, exact: bool) -> SimpleNamespace:
                return SimpleNamespace(count=7)

        with configured_app(USE_RAG="true", QDRANT_URL="https://qdrant.example") as (_, app):
            app.state.rag_pipeline = SimpleNamespace(
                collection_name="resume",
                qdrant_client=FakeQdrantClient(),
                keyword_documents_count=7,
                keyword_index_ready=True,
                corpus_current=True,
                dense_retrieval_status="degraded",
            )
            response = TestClient(app).get("/health/rag")

        payload = response.json()
        self.assertTrue(payload["indexes_ready"])
        self.assertEqual(payload["dense_retrieval_status"], "degraded")
        self.assertFalse(payload["retrieval_ready"])

    def test_rag_health_requires_a_successful_dense_query(self) -> None:
        class FakeQdrantClient:
            def collection_exists(self, collection_name: str) -> bool:
                return True

            def count(self, collection_name: str, exact: bool) -> SimpleNamespace:
                return SimpleNamespace(count=7)

        with configured_app(USE_RAG="true", QDRANT_URL="https://qdrant.example") as (_, app):
            app.state.rag_pipeline = SimpleNamespace(
                collection_name="resume",
                qdrant_client=FakeQdrantClient(),
                keyword_documents_count=7,
                keyword_index_ready=True,
                corpus_current=True,
                dense_retrieval_status="not_tested",
            )
            response = TestClient(app).get("/health/rag")

        payload = response.json()
        self.assertTrue(payload["indexes_ready"])
        self.assertEqual(payload["dense_retrieval_status"], "not_tested")
        self.assertFalse(payload["retrieval_ready"])

    def test_rag_health_rejects_stale_corpus_with_matching_counts(self) -> None:
        class FakeQdrantClient:
            def collection_exists(self, collection_name: str) -> bool:
                return True

            def count(self, collection_name: str, exact: bool) -> SimpleNamespace:
                return SimpleNamespace(count=7)

        with configured_app(USE_RAG="true", QDRANT_URL="https://qdrant.example") as (_, app):
            app.state.rag_pipeline = SimpleNamespace(
                collection_name="resume",
                qdrant_client=FakeQdrantClient(),
                keyword_documents_count=7,
                keyword_index_ready=True,
                corpus_current=False,
                dense_retrieval_status="healthy",
            )
            response = TestClient(app).get("/health/rag")

        payload = response.json()
        self.assertTrue(payload["vector_db_live"])
        self.assertFalse(payload["indexes_ready"])
        self.assertFalse(payload["retrieval_ready"])


class TestApiKeyNeverLeaks(unittest.TestCase):
    """Prove no /api/chat error path can expose the Anthropic API key."""

    def _chat_response(self, exc: BaseException):
        """Send one chat request with the Anthropic client patched to raise `exc`."""
        with configured_app(
            ANTHROPIC_API_KEY=SENTINEL_KEY,
            USE_RAG="false",
        ) as (main, app):
            main.AsyncAnthropic = _fake_client_factory(exc)
            client = TestClient(app)
            return main, client.post("/api/chat", json={"message": "Tell me about Dakota"})

    def test_rate_limit_returns_busy_message_without_key(self) -> None:
        main, response = self._chat_response(_rate_limit_error())

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], main.BUSY_MESSAGE)
        # The secret must not appear anywhere in what the client receives.
        self.assertNotIn(SENTINEL_KEY, response.text)

    def test_generic_anthropic_error_hides_key(self) -> None:
        _, response = self._chat_response(
            AnthropicError(f"upstream failure for {SENTINEL_KEY}")
        )

        self.assertEqual(response.status_code, 502)
        self.assertNotIn(SENTINEL_KEY, response.text)
        # A generic, non-revealing message is returned instead of the exception text.
        self.assertIn("try again", response.json()["detail"].lower())

    def test_unexpected_error_hides_key(self) -> None:
        _, response = self._chat_response(
            RuntimeError(f"boom while using {SENTINEL_KEY}")
        )

        self.assertEqual(response.status_code, 500)
        self.assertNotIn(SENTINEL_KEY, response.text)
        self.assertIn("unexpected", response.json()["detail"].lower())

    def test_app_never_runs_in_debug_mode(self) -> None:
        # Starlette's debug traceback page renders frame-local variables (which would
        # include the API key). The app must never be constructed in debug mode.
        with configured_app(ANTHROPIC_API_KEY=SENTINEL_KEY) as (_, app):
            self.assertFalse(app.debug)


if __name__ == "__main__":
    unittest.main()

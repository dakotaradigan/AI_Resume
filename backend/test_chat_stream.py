"""Tests for the SSE chat endpoint, model router, and FOLLOWUPS contract."""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

# Prevent importing backend.main from initializing an external RAG connection.
os.environ["USE_RAG"] = "false"

import main
from anthropic import AnthropicError
from config import Settings


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

SIMPLE_MESSAGE = "Does Dakota know Python?"  # short, no multi-part markers -> fast-path
COMPLEX_MESSAGE = (
    "Compare Dakota's product management experience, his AI engineering work, "
    "and his operations background, and explain which roles fit him best?"
)


def make_settings(*, free_chat_limit: int = 20, use_rag: bool = False) -> Settings:
    return Settings(
        anthropic_api_key="test-anthropic-key",
        anthropic_model="test-opus",
        anthropic_max_tokens=256,
        environment="test",
        data_dir=DATA_DIR,
        anthropic_model_simple="test-sonnet",
        anthropic_router_model="test-router",
        rate_limit_requests_per_minute=100,
        session_max_age_seconds=3600,
        api_timeout_seconds=5.0,
        max_user_message_chars=2000,
        admin_token="test-admin-token",
        redis_url="",
        chat_password="test-chat-password",
        free_chat_limit=free_chat_limit,
        openai_api_key="",
        qdrant_url=None,
        qdrant_api_key="",
        use_rag=use_rag,
    )


class FakeStreamContext:
    """Mimics anthropic's messages.stream() async context manager."""

    def __init__(self, chunks: list[str], error_kind: str | None, error_at: int):
        self._chunks = chunks
        self._error_kind = error_kind
        self._error_at = error_at

    async def __aenter__(self) -> "FakeStreamContext":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    @property
    def text_stream(self):
        async def gen():
            for idx, chunk in enumerate(self._chunks):
                if self._error_kind is not None and idx == self._error_at:
                    if self._error_kind == "cancel":
                        raise asyncio.CancelledError()
                    raise AnthropicError("simulated mid-stream failure")
                yield chunk

        return gen()

    async def get_final_message(self) -> SimpleNamespace:
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="".join(self._chunks))]
        )


class FakeStreamingMessages:
    def __init__(
        self,
        chunks: list[str],
        router_label: str = "complex",
        error_kind: str | None = None,
        error_at: int = 0,
        router_raises: bool = False,
        fail_models: set[str] | None = None,
    ):
        self.chunks = chunks
        self.router_label = router_label
        self.error_kind = error_kind
        self.error_at = error_at
        self.router_raises = router_raises
        self.fail_models = fail_models or set()
        self.create_calls: list[dict] = []
        self.stream_calls: list[dict] = []

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        if self.router_raises:
            raise AnthropicError("router unavailable")
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.router_label)]
        )

    def stream(self, **kwargs) -> FakeStreamContext:
        self.stream_calls.append(kwargs)
        if kwargs.get("model") in self.fail_models:
            raise AnthropicError(f"model {kwargs['model']} unavailable")
        return FakeStreamContext(self.chunks, self.error_kind, self.error_at)


class FakeAnthropic:
    messages_api: FakeStreamingMessages | None = None
    models_api = None

    def __init__(self, **_kwargs) -> None:
        self.messages = type(self).messages_api
        self.models = type(self).models_api


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for frame in raw.strip().split("\n\n"):
        event_name = None
        data = None
        for line in frame.split("\n"):
            if line.startswith("event: "):
                event_name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if event_name is not None:
            events.append((event_name, data))
    return events


class ChatStreamTestCase(unittest.TestCase):
    def setUp(self) -> None:
        main._session_store = None
        main._starter_cache.clear()
        main._daily_conversation_count.clear()
        main.load_system_prompt.cache_clear()
        main.load_resume_context.cache_clear()
        main.load_resume_json_public.cache_clear()
        patcher = patch.object(main, "AsyncAnthropic", FakeAnthropic)
        patcher.start()
        self.addCleanup(patcher.stop)
        log_patcher = patch.object(main, "log_query")
        log_patcher.start()
        self.addCleanup(log_patcher.stop)

    def tearDown(self) -> None:
        main._session_store = None
        main.load_system_prompt.cache_clear()
        main.load_resume_context.cache_clear()
        main.load_resume_json_public.cache_clear()

    def build_client(self, settings: Settings) -> TestClient:
        with (
            patch.object(main, "get_settings", return_value=settings),
            patch.object(main, "_initialize_rag", return_value=None),
        ):
            return TestClient(main.build_app())

    def stream_events(self, client: TestClient, message: str, session_id: str | None = None) -> list[tuple[str, dict]]:
        payload = {"message": message}
        if session_id:
            payload["session_id"] = session_id
        with client.stream("POST", "/api/chat/stream", json=payload) as response:
            self.assertEqual(response.status_code, 200)
            self.assertTrue(
                response.headers["content-type"].startswith("text/event-stream")
            )
            raw = "".join(response.iter_text())
        return parse_sse(raw)


class TestEventOrdering(ChatStreamTestCase):
    def test_event_sequence_and_reply_assembly(self) -> None:
        FakeAnthropic.messages_api = FakeStreamingMessages(
            ["Dakota is ", "PCAP-certified.", "\nFOLLOWUPS: q1 | q2 | q3"]
        )
        with self.build_client(make_settings()) as client:
            events = self.stream_events(client, SIMPLE_MESSAGE)

        names = [name for name, _ in events]
        self.assertEqual(names[0], "session")
        self.assertEqual(
            names[1:5],
            ["status", "status", "status", "status"],
            f"expected 4 status events, got {names}",
        )
        self.assertEqual(names[-1], "done")
        self.assertIn("delta", names)

        stages = [d["stage"] for name, d in events if name == "status"]
        self.assertEqual(stages, ["rag_search", "rag_search", "routing", "generation"])

        deltas = "".join(d["text"] for name, d in events if name == "delta")
        done = events[-1][1]
        # done.reply is the FOLLOWUPS-stripped concatenation of the deltas
        self.assertEqual(done["reply"], "Dakota is PCAP-certified.")
        self.assertTrue(deltas.startswith(done["reply"]))
        self.assertEqual(done["followups"], ["q1", "q2", "q3"])
        self.assertNotIn(main.FOLLOWUPS_MARKER, done["reply"])
        self.assertIsInstance(done["quota_remaining"], int)

    def test_fast_path_routes_to_simple_model_without_classifier(self) -> None:
        FakeAnthropic.messages_api = FakeStreamingMessages(["Yes."])
        with self.build_client(make_settings()) as client:
            events = self.stream_events(client, SIMPLE_MESSAGE)

        routing = next(d for name, d in events if name == "status" and d["stage"] == "routing")
        self.assertEqual(routing["reason"], "fast-path")
        self.assertEqual(routing["model"], "Sonnet")
        # Classifier never called on the fast path
        self.assertEqual(FakeAnthropic.messages_api.create_calls, [])
        self.assertEqual(
            FakeAnthropic.messages_api.stream_calls[0]["model"], "test-sonnet"
        )

    def test_complex_message_uses_classifier_and_primary_model(self) -> None:
        FakeAnthropic.messages_api = FakeStreamingMessages(
            ["Long answer."], router_label="complex"
        )
        with self.build_client(make_settings()) as client:
            events = self.stream_events(client, COMPLEX_MESSAGE)

        routing = next(d for name, d in events if name == "status" and d["stage"] == "routing")
        self.assertEqual(routing["reason"], "complex")
        self.assertEqual(len(FakeAnthropic.messages_api.create_calls), 1)
        self.assertEqual(
            FakeAnthropic.messages_api.create_calls[0]["model"], "test-router"
        )
        self.assertEqual(
            FakeAnthropic.messages_api.stream_calls[0]["model"], "test-opus"
        )


class TestGuardrailsBeforeStream(ChatStreamTestCase):
    def test_free_limit_is_plain_http_403_not_sse(self) -> None:
        FakeAnthropic.messages_api = FakeStreamingMessages(["Hi."])
        with self.build_client(make_settings(free_chat_limit=1)) as client:
            first = self.stream_events(client, SIMPLE_MESSAGE, session_id="quota-session")
            self.assertEqual(first[-1][0], "done")

            response = client.post(
                "/api/chat/stream",
                json={"message": SIMPLE_MESSAGE, "session_id": "quota-session"},
            )
            self.assertEqual(response.status_code, 403)
            self.assertIn("detail", response.json())

    def test_last_free_exchange_reports_zero_quota_remaining(self) -> None:
        FakeAnthropic.messages_api = FakeStreamingMessages(["Hi."])
        with self.build_client(make_settings(free_chat_limit=1)) as client:
            events = self.stream_events(client, SIMPLE_MESSAGE, session_id="quota-session")
        self.assertEqual(events[-1][1]["quota_remaining"], 0)


class TestStarterCache(ChatStreamTestCase):
    STARTER = "What's Dakota's background?"

    def test_cached_starter_streams_single_delta(self) -> None:
        main._starter_cache[self.STARTER.lower().rstrip("?") + "?"] = "Cached answer."
        FakeAnthropic.messages_api = FakeStreamingMessages(["should not be used"])
        with self.build_client(make_settings()) as client:
            events = self.stream_events(client, self.STARTER, session_id="fresh-1")

        names = [name for name, _ in events]
        self.assertEqual(names, ["session", "status", "delta", "done"])
        self.assertEqual(events[1][1]["stage"], "cached")
        self.assertEqual(events[-1][1]["reply"], "Cached answer.")
        self.assertEqual(FakeAnthropic.messages_api.stream_calls, [])

    def test_starter_cache_population_strips_followups(self) -> None:
        FakeAnthropic.messages_api = FakeStreamingMessages(
            ["Background answer.", "\nFOLLOWUPS: a | b"]
        )
        with self.build_client(make_settings()) as client:
            self.stream_events(client, self.STARTER, session_id="fresh-2")

        cache_key = self.STARTER.lower().rstrip("?") + "?"
        self.assertIn(cache_key, main._starter_cache)
        self.assertNotIn(main.FOLLOWUPS_MARKER, main._starter_cache[cache_key])


class TestModelFallback(ChatStreamTestCase):
    def test_failed_routed_model_falls_back_to_primary(self) -> None:
        # Fast-path routes SIMPLE_MESSAGE to test-sonnet; that model "fails"
        # (e.g. the org's key lacks access) and the primary must rescue it.
        FakeAnthropic.messages_api = FakeStreamingMessages(
            ["Rescued answer."], fail_models={"test-sonnet"}
        )
        with self.build_client(make_settings()) as client:
            events = self.stream_events(client, SIMPLE_MESSAGE)

        done = events[-1]
        self.assertEqual(done[0], "done")
        self.assertEqual(done[1]["reply"], "Rescued answer.")
        self.assertEqual(done[1]["model"], "Opus")
        models_tried = [c["model"] for c in FakeAnthropic.messages_api.stream_calls]
        self.assertEqual(models_tried, ["test-sonnet", "test-opus"])

    def test_primary_model_failure_still_errors(self) -> None:
        FakeAnthropic.messages_api = FakeStreamingMessages(
            ["never"], fail_models={"test-sonnet", "test-opus"}
        )
        with self.build_client(make_settings()) as client:
            events = self.stream_events(client, SIMPLE_MESSAGE)
        self.assertEqual(events[-1][0], "error")


class TestStreamErrors(ChatStreamTestCase):
    def test_mid_stream_anthropic_error_yields_error_event(self) -> None:
        FakeAnthropic.messages_api = FakeStreamingMessages(
            ["partial ", "never sent"], error_kind="anthropic", error_at=1
        )
        with self.build_client(make_settings()) as client:
            events = self.stream_events(client, SIMPLE_MESSAGE)

        names = [name for name, _ in events]
        self.assertEqual(names[-1], "error")
        self.assertNotIn("done", names)
        self.assertEqual(events[-1][1]["detail"], main.GENERIC_CHAT_ERROR)

    def test_cancelled_stream_does_not_persist_history(self) -> None:
        FakeAnthropic.messages_api = FakeStreamingMessages(
            ["partial "], error_kind="cancel", error_at=0
        )
        with self.build_client(make_settings()) as client:
            try:
                with client.stream(
                    "POST",
                    "/api/chat/stream",
                    json={"message": SIMPLE_MESSAGE, "session_id": "cancelled-session"},
                ) as response:
                    "".join(response.iter_text())
            except Exception:
                pass  # cancellation may surface as a transport error; that's fine

            store = main.get_session_store()
            history = asyncio.run(store.get_history("cancelled-session"))
            roles = [msg.get("role") for msg in history]
            self.assertNotIn("assistant", roles)


class TestNonStreamingContract(ChatStreamTestCase):
    def test_chat_sources_are_strings(self) -> None:
        FakeAnthropic.messages_api = FakeStreamingMessages(["Answer."])
        settings = make_settings(use_rag=True)
        with self.build_client(settings) as client:
            fake_pipeline = SimpleNamespace(
                search=lambda query, limit, score_threshold: [
                    {"text": "chunk", "title": "Ben AI: Assistant", "type": "project",
                     "score": 0.61, "timeframe": ""},
                ]
            )
            client.app.state.rag_pipeline = fake_pipeline
            response = client.post("/api/chat", json={"message": SIMPLE_MESSAGE})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["used_rag"])
        self.assertEqual(data["sources"], ["Ben AI: Assistant"])
        for source in data["sources"]:
            self.assertIsInstance(source, str)

    def test_chat_reply_has_followups_stripped(self) -> None:
        FakeAnthropic.messages_api = FakeStreamingMessages(["ignored"])

        async def fake_create(**kwargs):
            FakeAnthropic.messages_api.create_calls.append(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(
                    type="text", text="Plain answer.\nFOLLOWUPS: x | y"
                )]
            )

        FakeAnthropic.messages_api.create = fake_create
        with self.build_client(make_settings()) as client:
            response = client.post("/api/chat", json={"message": SIMPLE_MESSAGE})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "Plain answer.")


class TestRouterUnits(unittest.TestCase):
    def test_fast_path_rules(self) -> None:
        self.assertTrue(main._is_fast_path_simple("Does Dakota know Python?"))
        self.assertFalse(main._is_fast_path_simple("Python, SQL?"))  # comma
        self.assertFalse(main._is_fast_path_simple("Python and SQL?"))  # " and "
        self.assertFalse(main._is_fast_path_simple("What? Why?"))  # two questions
        self.assertFalse(main._is_fast_path_simple("x" * 120))  # long

    def test_router_error_fails_safe_to_primary_model(self) -> None:
        settings = make_settings()
        client = SimpleNamespace(messages=FakeStreamingMessages([], router_raises=True))
        model, reason = asyncio.run(
            main._route_model(COMPLEX_MESSAGE, client, settings)
        )
        self.assertEqual(model, "test-opus")
        self.assertEqual(reason, "router-error")

    def test_router_simple_label_routes_to_simple_model(self) -> None:
        settings = make_settings()
        client = SimpleNamespace(
            messages=FakeStreamingMessages([], router_label="simple")
        )
        model, reason = asyncio.run(
            main._route_model(COMPLEX_MESSAGE, client, settings)
        )
        self.assertEqual(model, "test-sonnet")
        self.assertEqual(reason, "simple")


class TestSamplingParams(unittest.TestCase):
    def test_temperature_omitted_for_models_that_reject_it(self) -> None:
        for model in (
            "claude-sonnet-5",
            "claude-opus-4-8",
            "claude-opus-4-7",
            "claude-fable-5",
            "claude-mythos-5",
        ):
            self.assertEqual(main._sampling_kwargs(model, 0.1), {}, model)

    def test_temperature_kept_for_older_models(self) -> None:
        for model in (
            "claude-sonnet-4-5-20250929",
            "claude-haiku-4-5-20251001",
            "claude-opus-4-5-20251101",
            "test-opus",
        ):
            self.assertEqual(
                main._sampling_kwargs(model, 0.1), {"temperature": 0.1}, model
            )


class TestModelIdGuard(unittest.TestCase):
    def test_malformed_claude_ids_are_flagged(self) -> None:
        import dataclasses
        from test_chat_stream import make_settings as _ms  # self-import safe in unittest

        bad = dataclasses.replace(_ms(), anthropic_model="Claude-Opus-4.8")
        with self.assertLogs("resume-assistant", level="ERROR") as captured:
            main._warn_on_suspicious_model_ids(bad)
        self.assertTrue(any("ANTHROPIC_MODEL" in line for line in captured.output))

    def test_valid_and_non_claude_ids_pass_silently(self) -> None:
        import dataclasses

        ok = dataclasses.replace(
            make_settings(),
            anthropic_model="claude-opus-4-8",
            anthropic_model_simple="claude-sonnet-5",
            anthropic_router_model="claude-haiku-4-5-20251001",
        )
        with self.assertNoLogs("resume-assistant", level="ERROR"):
            main._warn_on_suspicious_model_ids(ok)
        # Test fixtures like "test-opus" are not claude ids and must not warn.
        with self.assertNoLogs("resume-assistant", level="ERROR"):
            main._warn_on_suspicious_model_ids(make_settings())


class TestModelsHealth(ChatStreamTestCase):
    def test_reports_ok_and_error_per_configured_model(self) -> None:
        class FakeModelsAPI:
            async def retrieve(self, model_id):
                if model_id == "test-sonnet":
                    raise AnthropicError("This model is not available to your organization")
                return SimpleNamespace(id=model_id)

        FakeAnthropic.messages_api = FakeStreamingMessages(["x"])
        FakeAnthropic.models_api = FakeModelsAPI()
        self.addCleanup(lambda: setattr(FakeAnthropic, "models_api", None))

        with self.build_client(make_settings()) as client:
            response = client.get("/health/models")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["ANTHROPIC_MODEL"]["status"], "ok")
        self.assertEqual(data["ANTHROPIC_ROUTER_MODEL"]["status"], "ok")
        self.assertEqual(data["ANTHROPIC_MODEL_SIMPLE"]["status"], "error")
        self.assertIn("not available", data["ANTHROPIC_MODEL_SIMPLE"]["detail"])


class TestFollowupsSplit(unittest.TestCase):
    def test_marker_line_is_split(self) -> None:
        reply, followups = main._split_followups("Answer.\nFOLLOWUPS: a | b | c")
        self.assertEqual(reply, "Answer.")
        self.assertEqual(followups, ["a", "b", "c"])

    def test_no_marker_returns_reply_unchanged(self) -> None:
        reply, followups = main._split_followups("Answer with no marker.")
        self.assertEqual(reply, "Answer with no marker.")
        self.assertEqual(followups, [])

    def test_followups_capped_at_three(self) -> None:
        _, followups = main._split_followups("A.\nFOLLOWUPS: a | b | c | d | e")
        self.assertEqual(followups, ["a", "b", "c"])

    def test_marker_mid_text_is_not_split(self) -> None:
        text = "The FOLLOWUPS: feature emits chips.\nMore prose."
        reply, followups = main._split_followups(text)
        self.assertEqual(reply, text)
        self.assertEqual(followups, [])


if __name__ == "__main__":
    unittest.main()

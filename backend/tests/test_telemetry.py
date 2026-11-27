"""Tracing for MCP tool calls (app/telemetry.py).

Spans are collected in memory: one SDK provider for the whole run, with an
InMemorySpanExporter behind a SimpleSpanProcessor (synchronous, so a span can
be read as soon as it ends). Tool calls go through the real MCP endpoint, as
in test_mcp_tools.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

# Prevent importing app.main from initializing an external RAG connection.
os.environ["USE_RAG"] = "false"

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app import mcp_server, telemetry
from app.chat_service import UNEXPECTED_ERROR_MESSAGE
from app.constants import CHAT_LIMIT_MESSAGE
from app.telemetry import MAX_CONTENT_CHARS, content_attribute

from tests.test_mcp_tools import REPLY, McpTestCase, mcp_call, tool_json, tool_result

EXPORTER = InMemorySpanExporter()
IP = "203.0.113.9"
QUESTION = "Does Dakota know Python?"


def setUpModule() -> None:
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(EXPORTER))


class TracingTestCase(McpTestCase):
    def setUp(self) -> None:
        super().setUp()
        EXPORTER.clear()

    def capture(self, on: bool) -> None:
        patcher = patch.object(telemetry, "_capture_content", on)
        patcher.start()
        self.addCleanup(patcher.stop)

    def only_tool_span(self):
        spans = [s for s in EXPORTER.get_finished_spans() if s.name.startswith("execute_tool")]
        self.assertEqual(len(spans), 1, [s.name for s in spans])
        return spans[0]

    def ask(self, question: str = QUESTION, **settings_overrides) -> None:
        with self.build_client(self.trusted(**settings_overrides)) as client:
            tool_json(mcp_call(client, "ask", {"question": question}, ip=IP))


class TestToolSpans(TracingTestCase):
    def test_a_tool_call_is_one_execute_tool_span(self) -> None:
        self.ask()
        span = self.only_tool_span()
        self.assertEqual(span.name, "execute_tool ask")
        self.assertEqual(span.attributes["gen_ai.operation.name"], "execute_tool")
        self.assertEqual(span.attributes["gen_ai.tool.name"], "ask")
        self.assertEqual(span.status.status_code, StatusCode.UNSET)

    def test_get_resume_is_traced_too(self) -> None:
        with self.build_client(self.trusted()) as client:
            tool_json(mcp_call(client, "get_resume", {}))
        self.assertEqual(self.only_tool_span().name, "execute_tool get_resume")

    def test_content_is_not_recorded_by_default(self) -> None:
        self.capture(False)
        self.ask()
        attributes = self.only_tool_span().attributes
        self.assertNotIn("gen_ai.tool.call.arguments", attributes)
        self.assertNotIn("gen_ai.tool.call.result", attributes)

    def test_capture_records_what_the_agent_sent_and_got_back(self) -> None:
        self.capture(True)
        self.ask()
        attributes = self.only_tool_span().attributes
        self.assertIn(QUESTION, attributes["gen_ai.tool.call.arguments"])
        self.assertIn(REPLY, attributes["gen_ai.tool.call.result"])

    def test_a_failure_while_recording_never_fails_the_tool_call(self) -> None:
        # Tracing is a side channel: a bug in it may cost an attribute, never
        # the caller's answer.
        self.capture(True)
        with patch.object(telemetry, "content_attribute", side_effect=TypeError("bug")):
            self.ask()
        self.assertNotIn("gen_ai.tool.call.arguments", self.only_tool_span().attributes)


class TestToolErrors(TracingTestCase):
    def test_a_refusal_marks_the_span_failed_with_the_message_the_caller_saw(self) -> None:
        # The security signal: a caller hitting the quota is visible in the
        # trace even with content capture off.
        with self.build_client(self.trusted(free_chat_limit=1)) as client:
            tool_result(mcp_call(client, "ask", {"question": "Hello?"}, ip=IP))
            EXPORTER.clear()
            is_error, _ = tool_result(mcp_call(client, "ask", {"question": "Again?"}, ip=IP))
        self.assertTrue(is_error)
        span = self.only_tool_span()
        self.assertEqual(span.status.status_code, StatusCode.ERROR)
        self.assertIn(CHAT_LIMIT_MESSAGE, span.status.description)
        self.assertEqual(span.attributes["error.type"], "403")

    def test_an_internal_error_leaves_no_exception_text_on_the_span(self) -> None:
        # The default span behavior records the exception message and
        # traceback; an upstream error's text can carry a credential.
        boom = RuntimeError("upstream said sk-ant-SECRETSECRETSECRET")
        with self.build_client(self.trusted()) as client:
            with patch.object(mcp_server, "run_json_chat_turn", side_effect=boom):
                tool_result(mcp_call(client, "ask", {"question": "Hello?"}, ip=IP))
        span = self.only_tool_span()
        self.assertEqual(span.status.description, UNEXPECTED_ERROR_MESSAGE)
        self.assertEqual(span.attributes["error.type"], "RuntimeError")
        self.assertEqual(len(span.events), 0)
        self.assertNotIn("SECRET", repr(dict(span.attributes)))


class TestContentAttribute(unittest.TestCase):
    """The contract for content_attribute, whatever its implementation."""

    def test_returns_a_readable_string_for_tool_arguments(self) -> None:
        out = content_attribute({"question": QUESTION, "session_id": None})
        self.assertIsInstance(out, str)
        self.assertIn(QUESTION, out)

    def test_is_never_longer_than_the_cap(self) -> None:
        out = content_attribute({"job_description": "x" * 50_000})
        self.assertLessEqual(len(out), MAX_CONTENT_CHARS)

    def test_credentials_are_redacted(self) -> None:
        # A caller can paste anything into a tool argument, a key included.
        out = content_attribute({"question": "my key is sk-ant-abcdefghijklmnop"})
        self.assertNotIn("abcdefghijklmnop", out)


if __name__ == "__main__":
    unittest.main()

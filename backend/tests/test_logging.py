"""Credential redaction in logs, and the request id on responses and records."""

from __future__ import annotations

import json
import logging
import os
import sys
import unittest

# Prevent importing app.main from initializing an external RAG connection.
os.environ["USE_RAG"] = "false"

from app.logging_setup import JsonLogFormatter, redact
from app.request_context import RequestContextFilter, accept_request_id, request_id_var

from tests.test_chat_stream import ChatStreamTestCase, make_settings

# Fixtures are assembled at runtime so that no committed line is itself
# secret-shaped: the CI secret scan reads every commit in the history.
BEARER = "Bearer " + "abcdef1234567890"
ANTHROPIC_KEY = "sk-ant-" + "api03-abcdefghijkl"
OPENAI_KEY = "sk-proj-" + "abcdefghijklmnop"
AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
PEM_BEGIN = "-----BEGIN " + "PRIVATE KEY-----"
PEM_END = "-----END " + "PRIVATE KEY-----"


class TestRedact(unittest.TestCase):
    def test_credential_shapes_are_scrubbed(self) -> None:
        cases = {
            f"Authorization: {BEARER}": ("abcdef1234567890", "Bearer ***"),
            f"key {ANTHROPIC_KEY} leaked": ("api03-abcdefghijkl", "sk-ant-***"),
            f"openai {OPENAI_KEY}": ("abcdefghijklmnop", "sk-proj-***"),
            f"aws {AWS_KEY} id": ("IOSFODNN7EXAMPLE", "AKIA***"),
            "redis://default:hunter2@host:6379/0": ("hunter2", "redis://***:***@host:6379/0"),
            "GET /x?api_key=abc123xyz&page=1": ("abc123xyz", "api_key=***&page=1"),
            f"pem {PEM_BEGIN}\nMIIEvQIBADANB\n{PEM_END} end": (
                "MIIEvQIBADANB",
                f"{PEM_BEGIN} *** {PEM_END}",
            ),
        }
        for text, (secret, expected) in cases.items():
            with self.subTest(text=text):
                scrubbed = redact(text)
                self.assertNotIn(secret, scrubbed)
                self.assertIn(expected, scrubbed)

    def test_clean_text_is_unchanged(self) -> None:
        line = "Model usage: model=claude-sonnet-5 route=simple input=120 output=40"
        self.assertEqual(redact(line), line)


class TestJsonFormatter(unittest.TestCase):
    def test_message_and_traceback_are_redacted_and_carry_the_request_id(self) -> None:
        # Tracebacks quote the raising source line, so the value lives in a
        # variable: the line itself must not carry the secret.
        upstream_message = "upstream said: " + "Bearer " + "secrettoken12345"
        try:
            raise ValueError(upstream_message)
        except ValueError:
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            "app.test", logging.ERROR, __file__, 1,
            "call failed with key " + "sk-ant-" + "api03-leakedvalue", None, exc_info,
        )
        record.request_id = "req-42"
        entry = json.loads(JsonLogFormatter().format(record))
        self.assertEqual(entry["request_id"], "req-42")
        self.assertNotIn("leakedvalue", entry["message"])
        self.assertNotIn("secrettoken12345", entry["exc"])
        self.assertIn("Bearer ***", entry["exc"])

    def test_no_request_id_outside_a_request(self) -> None:
        record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "booted", None, None)
        self.assertNotIn("request_id", json.loads(JsonLogFormatter().format(record)))


class TestRequestId(ChatStreamTestCase):
    def test_every_response_carries_a_request_id(self) -> None:
        with self.build_client(make_settings()) as client:
            minted = client.get("/health").headers["x-request-id"]
            self.assertRegex(minted, r"^[0-9a-f]{32}$")
            echoed = client.get("/health", headers={"X-Request-ID": "edge-7f3a.1"})
            self.assertEqual(echoed.headers["x-request-id"], "edge-7f3a.1")
            oversized = client.get("/health", headers={"X-Request-ID": "x" * 200})
            self.assertRegex(oversized.headers["x-request-id"], r"^[0-9a-f]{32}$")

    def test_malformed_ids_are_replaced(self) -> None:
        self.assertEqual(accept_request_id("abc-123.z_9"), "abc-123.z_9")
        for bad in ("", None, "has space", "semi;colon", "x" * 129):
            with self.subTest(bad=bad):
                self.assertRegex(accept_request_id(bad), r"^[0-9a-f]{32}$")

    def test_filter_stamps_the_current_id(self) -> None:
        record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "hi", None, None)
        token = request_id_var.set("req-99")
        try:
            self.assertTrue(RequestContextFilter().filter(record))
        finally:
            request_id_var.reset(token)
        self.assertEqual(record.request_id, "req-99")

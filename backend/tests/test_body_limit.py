"""The request body cap: an oversized body is refused before it is buffered,
and the largest legitimate request still fits."""

from __future__ import annotations

import dataclasses
import json
import os

# Prevent importing app.main from initializing an external RAG connection.
os.environ["USE_RAG"] = "false"

from app import session_store
from app.middleware import BODY_TOO_LARGE_MESSAGE, max_request_body_bytes

from tests.test_chat_stream import (
    ChatStreamTestCase,
    FakeAnthropic,
    FakeStreamingMessages,
    make_settings,
)


class TestBodySizeLimit(ChatStreamTestCase):
    def setUp(self) -> None:
        super().setUp()
        FakeAnthropic.messages_api = FakeStreamingMessages(["## Strong Matches\n- Yes"])

    def assert_refused_unread(self, response) -> None:
        self.assertEqual(response.status_code, 413)
        # The cap's own message: the route (and its "Message too long" check,
        # which only runs after the whole body is in memory) never ran.
        self.assertEqual(response.json()["detail"], BODY_TOO_LARGE_MESSAGE)
        self.assertEqual(sum(session_store._daily_conversation_count.values()), 0)
        self.assertEqual(FakeAnthropic.messages_api.stream_calls, [])

    def test_declared_oversize_body_is_refused_before_the_route(self) -> None:
        settings = make_settings()
        oversize = "A" * (max_request_body_bytes(settings) + 1)
        with self.build_client(settings) as client:
            response = client.post("/api/chat/stream", json={"message": oversize})
        self.assert_refused_unread(response)

    def test_oversize_body_with_no_declared_length_is_refused(self) -> None:
        # A chunked upload carries no Content-Length, so it is counted as it
        # arrives instead.
        settings = make_settings()
        body = json.dumps({"message": "A" * (max_request_body_bytes(settings) + 1)}).encode()

        def chunks():
            for start in range(0, len(body), 64 * 1024):
                yield body[start:start + 64 * 1024]

        with self.build_client(settings) as client:
            response = client.post(
                "/api/chat/stream",
                content=chunks(),
                headers={"Content-Type": "application/json"},
            )
        self.assert_refused_unread(response)

    def test_full_length_jd_of_wide_characters_fits(self) -> None:
        # The worst legitimate case: a job description at the character limit
        # in which every character is the widest JSON can carry.
        settings = make_settings()
        widest_jd = "\N{GRINNING FACE}" * settings.max_jd_chars
        # json.dumps escapes each one as a surrogate pair: 12 bytes per character.
        escaped = json.dumps({"jd_text": widest_jd}).encode()
        self.assertLess(len(escaped), max_request_body_bytes(settings))
        with self.build_client(settings) as client:
            response = client.post(
                "/api/jd-match",
                content=escaped,
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("event: done", response.text)

    def test_cap_follows_the_text_limits(self) -> None:
        # Raising MAX_JD_CHARS must raise the cap with it, or a longer paste
        # the settings allow would be refused here.
        settings = make_settings()
        longer = dataclasses.replace(settings, max_jd_chars=settings.max_jd_chars * 4)
        self.assertGreater(max_request_body_bytes(longer), max_request_body_bytes(settings))
        self.assertGreater(max_request_body_bytes(longer), longer.max_jd_chars * 12)

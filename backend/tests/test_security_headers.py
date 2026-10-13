"""Security headers are pinned exactly: a drift in the policy fails here
instead of surfacing, if at all, in a browser console."""

from __future__ import annotations

import os
import unittest

# Prevent importing app.main from initializing an external RAG connection.
os.environ["USE_RAG"] = "false"

from app.middleware import CONTENT_SECURITY_POLICY

from tests.test_chat_stream import (
    ChatStreamTestCase,
    FakeAnthropic,
    FakeStreamingMessages,
    make_settings,
)
from tests.test_security import make_settings as make_production_settings

EXPECTED_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
HSTS = "max-age=63072000; includeSubDomains"


def assert_security_headers(case: unittest.TestCase, headers, *, production: bool) -> None:
    case.assertEqual(headers["content-security-policy"], EXPECTED_CSP)
    case.assertEqual(headers["x-frame-options"], "DENY")
    case.assertEqual(headers["x-content-type-options"], "nosniff")
    case.assertEqual(headers["referrer-policy"], "strict-origin-when-cross-origin")
    if production:
        case.assertEqual(headers["strict-transport-security"], HSTS)
    else:
        # HSTS would break plain-http local development.
        case.assertNotIn("strict-transport-security", headers)


class TestSecurityHeaders(ChatStreamTestCase):
    def test_policy_constant_is_pinned(self) -> None:
        self.assertEqual(CONTENT_SECURITY_POLICY, EXPECTED_CSP)

    def test_every_response_kind_carries_the_headers(self) -> None:
        FakeAnthropic.messages_api = FakeStreamingMessages(["Hi."])
        with self.build_client(make_settings()) as client:
            for path in ("/", "/health", "/api/resume", "/no-such-page"):
                with self.subTest(path=path):
                    assert_security_headers(self, client.get(path).headers, production=False)
            self.assertEqual(client.get("/no-such-page").status_code, 404)
            with client.stream(
                "POST", "/api/chat/stream", json={"message": "Does Dakota know Python?"}
            ) as response:
                assert_security_headers(self, response.headers, production=False)

    def test_production_adds_hsts(self) -> None:
        with self.build_client(make_production_settings()) as client:
            assert_security_headers(self, client.get("/health").headers, production=True)

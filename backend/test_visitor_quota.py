"""Tests for server-minted visitor identity: cookies, quota rekey, daily budget."""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

# Prevent importing backend.main from initializing an external RAG connection.
os.environ["USE_RAG"] = "false"

import main
from analytics.analytics import anonymize_session_id
from config import Settings
from test_chat_stream import FakeAnthropic, FakeStreamingMessages, make_settings


COOKIE = "resume_assistant_visitor_id"


class VisitorQuotaTestCase(unittest.TestCase):
    def setUp(self) -> None:
        main._session_store = None
        main._starter_cache.clear()
        main._daily_conversation_count.clear()
        main.load_system_prompt.cache_clear()
        main.load_jd_match_prompt.cache_clear()
        main.load_resume_context.cache_clear()
        main.load_resume_json_public.cache_clear()
        FakeAnthropic.messages_api = FakeStreamingMessages(["Hello."])
        patcher = patch.object(main, "AsyncAnthropic", FakeAnthropic)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        main._session_store = None
        main.load_system_prompt.cache_clear()
        main.load_jd_match_prompt.cache_clear()
        main.load_resume_context.cache_clear()
        main.load_resume_json_public.cache_clear()

    def build_client(self, settings: Settings) -> TestClient:
        with (
            patch.object(main, "get_settings", return_value=settings),
            patch.object(main, "_initialize_rag", return_value=None),
        ):
            return TestClient(main.build_app())

    def chat(self, client: TestClient, session_id: str, message: str = "Does Dakota know Python?"):
        return client.post(
            "/api/chat/stream", json={"message": message, "session_id": session_id}
        )


class TestVisitorCookie(VisitorQuotaTestCase):
    def test_cookie_minted_when_absent(self) -> None:
        with (
            self.build_client(make_settings()) as client,
            patch.object(main, "log_query"),
        ):
            response = self.chat(client, "s1")
        self.assertEqual(response.status_code, 200)
        set_cookie = response.headers.get("set-cookie", "")
        self.assertIn(COOKIE, set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=lax", set_cookie)
        # Test env is not production: Secure must be absent so local dev works.
        self.assertNotIn("Secure", set_cookie)

    def test_valid_cookie_is_reused_and_malformed_replaced(self) -> None:
        with (
            self.build_client(make_settings()) as client,
            patch.object(main, "log_query"),
        ):
            first = self.chat(client, "s1")
            minted = first.cookies.get(COOKIE)
            self.assertTrue(minted)
            # TestClient persists cookies: the next response re-sets the SAME id.
            second = self.chat(client, "s1")
            self.assertEqual(second.cookies.get(COOKIE), minted)

            # A tampered, non-UUID cookie is replaced with a fresh mint.
            client.cookies.set(COOKIE, "totally-not-a-uuid")
            third = self.chat(client, "s1")
            replaced = third.cookies.get(COOKIE)
            self.assertTrue(replaced)
            self.assertNotEqual(replaced, "totally-not-a-uuid")


class TestQuotaRekeyedToVisitor(VisitorQuotaTestCase):
    def test_new_session_id_does_not_reset_quota(self) -> None:
        """The old bypass: clear localStorage -> new session_id -> fresh quota."""
        with (
            self.build_client(make_settings(free_chat_limit=1)) as client,
            patch.object(main, "log_query"),
        ):
            self.assertEqual(self.chat(client, "session-A").status_code, 200)
            # Same visitor cookie, brand-new session id: still blocked.
            blocked = self.chat(client, "session-B")
            self.assertEqual(blocked.status_code, 403)

    def test_unlock_persists_across_session_ids_and_mints_cookie(self) -> None:
        settings = make_settings(free_chat_limit=1)
        with (
            self.build_client(settings) as client,
            patch.object(main, "log_query"),
        ):
            # Unlock FIRST (no prior cookie): must mint one and key unlock to it.
            unlock = client.post(
                "/api/unlock", json={"password": "test-chat-password"}
            )
            self.assertEqual(unlock.status_code, 200)
            self.assertTrue(unlock.json()["success"])
            self.assertIn(COOKIE, unlock.headers.get("set-cookie", ""))

            # Unlimited across arbitrary session ids on the same visitor.
            for sid in ("x1", "x2", "x3"):
                self.assertEqual(self.chat(client, sid).status_code, 200)

    def test_jd_budget_keyed_to_visitor_not_session(self) -> None:
        jd = "Requirements: 5+ years of experience in product management, SQL. " * 5
        with (
            self.build_client(make_settings()) as client,
            patch.object(main, "log_query"),
        ):
            # Default budget: ONE free analysis per visitor per day.
            self.assertEqual(
                client.post("/api/jd-match", json={"jd_text": jd, "session_id": "a"}).status_code,
                200,
            )
            # Second analysis on a fresh session id, same visitor: blocked —
            # the budget follows the cookie, not the session id.
            second = client.post("/api/jd-match", json={"jd_text": jd, "session_id": "b"})
            self.assertEqual(second.status_code, 403)
            self.assertEqual(second.json()["detail"], main.JD_LIMIT_MESSAGE)


class TestDailyBudgetReserveRelease(VisitorQuotaTestCase):
    def test_reserve_blocks_at_limit_and_release_returns_unit(self) -> None:
        store = main.SessionStore()

        async def scenario() -> tuple[bool, bool, bool]:
            first = await store.reserve_daily_conversation("2026-07-19", 1)
            second = await store.reserve_daily_conversation("2026-07-19", 1)
            await store.release_daily_conversation("2026-07-19")
            third = await store.reserve_daily_conversation("2026-07-19", 1)
            return first, second, third

        first, second, third = asyncio.run(scenario())
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertTrue(third)

    def test_reserve_is_atomic_under_concurrency(self) -> None:
        store = main.SessionStore()

        async def scenario() -> int:
            results = await asyncio.gather(
                *[store.reserve_daily_conversation("2026-07-19", 5) for _ in range(20)]
            )
            return sum(1 for r in results if r)

        self.assertEqual(asyncio.run(scenario()), 5)

    def test_failed_generation_releases_daily_unit(self) -> None:
        FakeAnthropic.messages_api = FakeStreamingMessages(
            ["never"], error_kind="anthropic", error_at=0
        )
        import dataclasses

        with (
            self.build_client(
                dataclasses.replace(make_settings(), daily_conversation_limit=1)
            ) as client,
            patch.object(main, "log_query"),
        ):
            failed = self.chat(client, "s1")
            self.assertEqual(failed.status_code, 200)  # SSE error event, budget released

            FakeAnthropic.messages_api = FakeStreamingMessages(["Recovered."])
            ok = self.chat(client, "s1")
            self.assertEqual(ok.status_code, 200)
            self.assertIn("event: done", ok.text)

    def test_guardrail_rejections_do_not_consume_budget(self) -> None:
        import dataclasses

        with (
            self.build_client(
                dataclasses.replace(make_settings(), daily_conversation_limit=1)
            ) as client,
            patch.object(main, "log_query"),
        ):
            too_long = self.chat(client, "s1", message="x" * 5000)
            self.assertEqual(too_long.status_code, 413)
            ok = self.chat(client, "s1")
            self.assertEqual(ok.status_code, 200)


class TestAnalyticsAnonymization(VisitorQuotaTestCase):
    def test_logged_ids_are_hashed_never_raw(self) -> None:
        captured: list[str] = []

        def capture(session_id, *args, **kwargs):
            captured.append(session_id)

        with (
            self.build_client(make_settings()) as client,
            patch.object(main, "log_query", side_effect=capture),
        ):
            self.chat(client, "raw-session-id-12345")

        self.assertTrue(captured)
        for logged in captured:
            self.assertNotEqual(logged, "raw-session-id-12345")
            self.assertNotIn("raw-session-id", logged)
            self.assertRegex(logged, r"^[0-9a-f]{16}$")

    def test_anonymize_is_deterministic_per_secret(self) -> None:
        a = anonymize_session_id("session-1", "secret-A")
        self.assertEqual(a, anonymize_session_id("session-1", "secret-A"))
        self.assertNotEqual(a, anonymize_session_id("session-1", "secret-B"))
        self.assertNotEqual(a, anonymize_session_id("session-2", "secret-A"))
        self.assertRegex(a, r"^[0-9a-f]{16}$")


if __name__ == "__main__":
    unittest.main()

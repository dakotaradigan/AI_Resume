"""Tests for /llms.txt and the password-gated /api/resume.pdf download."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

# Prevent importing backend.main from initializing an external RAG connection.
os.environ["USE_RAG"] = "false"

import main
from test_chat_stream import make_settings
from test_visitor_quota import VisitorQuotaTestCase


def _real_phone() -> str:
    resume_path = Path(__file__).resolve().parent.parent / "data" / "resume.json"
    data = json.loads(resume_path.read_text(encoding="utf-8"))
    return str(data.get("personal", {}).get("phone", ""))


class RenderCacheMixin(unittest.TestCase):
    def setUp(self) -> None:  # noqa: D102 - shared cache hygiene
        super().setUp()
        main.render_llms_text.cache_clear()
        main.render_resume_pdf.cache_clear()
        self.addCleanup(main.render_llms_text.cache_clear)
        self.addCleanup(main.render_resume_pdf.cache_clear)


class TestLlmsTxt(RenderCacheMixin, VisitorQuotaTestCase):
    def test_llms_txt_renders_from_resume_without_phone(self) -> None:
        with self.build_client(make_settings()) as client:
            response = client.get("/llms.txt")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers["content-type"])
        body = response.text
        self.assertIn("Dakota Radigan", body)
        self.assertIn("/mcp", body)
        self.assertIn("## Experience", body)
        phone = _real_phone()
        if phone:
            self.assertNotIn(phone, body)

    def test_llms_txt_cache_cleared_by_admin_endpoint(self) -> None:
        with self.build_client(make_settings()) as client:
            client.get("/llms.txt")
            self.assertEqual(main.render_llms_text.cache_info().currsize, 1)
            cleared = client.post(
                "/admin/cache/clear", headers={"X-Admin-Token": "test-admin-token"}
            )
            self.assertEqual(cleared.status_code, 200)
            self.assertEqual(main.render_llms_text.cache_info().currsize, 0)


class TestResumePdf(RenderCacheMixin, VisitorQuotaTestCase):
    def unlock(self, client) -> None:
        response = client.post(
            "/api/unlock", json={"password": "test-chat-password"}
        )
        self.assertTrue(response.json()["success"])

    def test_locked_visitor_gets_403_with_unlock_hint(self) -> None:
        with self.build_client(make_settings()) as client:
            response = client.get("/api/resume.pdf")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], main.PDF_LOCKED_MESSAGE)

    def test_unlocked_visitor_downloads_pdf(self) -> None:
        with self.build_client(make_settings()) as client:
            self.unlock(client)
            response = client.get("/api/resume.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("Dakota-Radigan-Resume.pdf", response.headers["content-disposition"])
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_pdf_renders_from_scrubbed_payload(self) -> None:
        # The renderer must read load_resume_json_public (phone already
        # stripped) — never the raw file. Guarded by patching the loader.
        marker = {"personal": {"name": "Scrub Check", "title": "PM"}}
        with patch.object(main, "load_resume_json_public", return_value=marker):
            main.render_resume_pdf.cache_clear()
            pdf = main.render_resume_pdf()
        self.assertTrue(pdf.startswith(b"%PDF-"))

    def test_download_rate_limited(self) -> None:
        with self.build_client(make_settings()) as client:
            for _ in range(5):
                self.assertEqual(client.get("/api/resume.pdf").status_code, 403)
            self.assertEqual(client.get("/api/resume.pdf").status_code, 429)


class TestMcpEndpoint(RenderCacheMixin, VisitorQuotaTestCase):
    def test_initialize_handshake_succeeds_on_bare_mcp_path(self) -> None:
        # Clients connect to exactly <domain>/mcp — no trailing slash. A
        # naive Mount 405s bare POSTs, so this guards the Route re-rooting.
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        }
        with self.build_client(make_settings()) as client:
            response = client.post(
                "/mcp",
                json=body,
                headers={"Accept": "application/json, text/event-stream"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("dakota-resume", response.text)


if __name__ == "__main__":
    unittest.main()

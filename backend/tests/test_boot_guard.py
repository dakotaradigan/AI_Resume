"""Production refuses to boot with client IPs it cannot trust."""

from __future__ import annotations

import dataclasses
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

# Prevent importing app.main from initializing an external RAG connection.
os.environ["USE_RAG"] = "false"

from app import main as app_main

from tests.test_security import make_settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def build(settings):
    with (
        patch.object(app_main, "get_settings", return_value=settings),
        patch.object(app_main, "initialize_rag", return_value=None),
    ):
        return app_main.build_app()


class TestBootGuard(unittest.TestCase):
    def production(self, **overrides):
        # make_settings() is production with the no-proxy override on;
        # start from the strict default here.
        fields = {"allow_untrusted_client_ips": False, **overrides}
        return dataclasses.replace(make_settings(), **fields)

    def test_production_without_proxy_trust_refuses_to_boot(self) -> None:
        with self.assertRaises(RuntimeError) as caught:
            build(self.production(trust_proxy_headers=False))
        self.assertIn("TRUST_PROXY_HEADERS", str(caught.exception))

    def test_production_boots_with_proxy_trust(self) -> None:
        self.assertIsNotNone(build(self.production(trust_proxy_headers=True)))

    def test_production_boots_with_the_explicit_override(self) -> None:
        settings = self.production(trust_proxy_headers=False, allow_untrusted_client_ips=True)
        self.assertIsNotNone(build(settings))

    def test_development_only_warns(self) -> None:
        settings = self.production(environment="development", trust_proxy_headers=False)
        with self.assertLogs("app.main", level="WARNING") as logs:
            build(settings)
        self.assertTrue(any("TRUST_PROXY_HEADERS" in line for line in logs.output))

    def test_railway_waits_for_health_before_switching_traffic(self) -> None:
        config = json.loads((REPO_ROOT / "railway.json").read_text(encoding="utf-8"))
        self.assertEqual(config["deploy"]["healthcheckPath"], "/health")

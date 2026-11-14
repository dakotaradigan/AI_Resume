"""Feature-use events: the public endpoint that records them, the summary
built from the logs, and the admin endpoints that show it."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

# Prevent importing app.main from initializing an external RAG connection.
os.environ["USE_RAG"] = "false"

from analytics import analytics
from analytics.analytics import USAGE_EVENTS, log_event, summarize_usage
from app.schemas import EventRequest

from tests.test_chat_stream import ChatStreamTestCase, make_settings

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
ADMIN = {"X-Admin-Token": "test-admin-token"}


def stamp(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def write_jsonl(path: Path, entries: list[dict], *, trailing: str = "") -> None:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries) + trailing, encoding="utf-8")


class AnalyticsFilesMixin:
    """Points the analytics module at a temporary directory, so a test never
    reads or writes the real logs."""

    def use_temp_logs(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.events_file = Path(tmp.name) / "events.jsonl"
        self.queries_file = Path(tmp.name) / "queries.jsonl"
        for name, path in (("EVENTS_FILE", self.events_file), ("ANALYTICS_FILE", self.queries_file)):
            patcher = patch.object(analytics, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)

    def logged_events(self) -> list[dict]:
        if not self.events_file.exists():
            return []
        return [json.loads(line) for line in self.events_file.read_text().splitlines()]


class TestEventContract(unittest.TestCase):
    def test_the_api_accepts_exactly_the_logged_event_names(self) -> None:
        # The schema repeats the names as a Literal (so FastAPI rejects the
        # rest); this keeps the two lists from drifting apart.
        accepted = EventRequest.model_fields["event"].annotation.__args__
        self.assertEqual(set(accepted), set(USAGE_EVENTS))


class TestSummarizeUsage(AnalyticsFilesMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.use_temp_logs()

    def test_counts_events_sessions_and_days_inside_the_window(self) -> None:
        write_jsonl(
            self.events_file,
            [
                {"timestamp": stamp(40), "session_id": "old", "event": "heatmap_open"},
                {"timestamp": stamp(2), "session_id": "a", "event": "heatmap_open"},
                {"timestamp": stamp(2), "session_id": "a", "event": "heatmap_open"},
                {"timestamp": stamp(1), "session_id": "b", "event": "heatmap_open"},
                {"timestamp": stamp(1), "session_id": "b", "event": "jd_upload"},
                {"timestamp": stamp(1), "session_id": "b", "event": "not_a_known_event"},
            ],
            trailing="not json at all\n",
        )
        summary = summarize_usage(30, now=NOW)
        self.assertEqual(summary["events"]["heatmap_open"], {"count": 3, "sessions": 2})
        self.assertEqual(summary["events"]["jd_upload"], {"count": 1, "sessions": 1})
        self.assertEqual(summary["events"]["heatmap_sample_open"], {"count": 0, "sessions": 0})
        self.assertEqual(
            summary["by_day"],
            {"2026-11-12": {"heatmap_open": 2}, "2026-11-13": {"heatmap_open": 1, "jd_upload": 1}},
        )
        self.assertEqual(summary["days"], 30)

    def test_query_log_splits_analyses_briefs_and_chat(self) -> None:
        write_jsonl(
            self.queries_file,
            [
                {"timestamp": stamp(1), "query": "[jd-analysis]", "route_reason": "jd-match"},
                {"timestamp": stamp(1), "query": "[jd-analysis]", "route_reason": "jd-match"},
                {"timestamp": stamp(1), "query": "[jd-brief] requested", "route_reason": "jd-match"},
                {"timestamp": stamp(1), "query": "Does Dakota know SQL?", "route_reason": "simple"},
                {"timestamp": stamp(1), "query": "A starter question"},
                {"timestamp": stamp(60), "query": "[jd-analysis]", "route_reason": "jd-match"},
            ],
        )
        summary = summarize_usage(30, now=NOW)
        self.assertEqual(
            (summary["fit_analyses"], summary["screening_briefs"], summary["chat_turns"]), (2, 1, 2)
        )
        self.assertEqual(summary["by_day"]["2026-11-13"]["fit_analyses"], 2)

    def test_no_logs_is_an_empty_summary(self) -> None:
        summary = summarize_usage(7, now=NOW)
        self.assertEqual(summary["fit_analyses"], 0)
        self.assertEqual(summary["by_day"], {})
        self.assertEqual(set(summary["events"]), set(USAGE_EVENTS))


class TestEventEndpoint(AnalyticsFilesMixin, ChatStreamTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.use_temp_logs()

    def test_event_is_logged_with_an_anonymized_session(self) -> None:
        with self.build_client(make_settings()) as client:
            response = client.post("/api/event", json={"event": "jd_upload", "session_id": "live-session-id"})
        self.assertEqual(response.status_code, 204)
        (entry,) = self.logged_events()
        self.assertEqual(entry["event"], "jd_upload")
        self.assertNotIn("live-session-id", json.dumps(entry))
        self.assertEqual(len(entry["session_id"]), 16)
        self.assertEqual(set(entry), {"timestamp", "session_id", "event"})

    def test_unknown_event_is_rejected_and_not_logged(self) -> None:
        with self.build_client(make_settings()) as client:
            response = client.post("/api/event", json={"event": "<script>", "session_id": "s"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.logged_events(), [])

    def test_past_the_rate_limit_events_are_dropped_quietly(self) -> None:
        with self.build_client(make_settings()) as client:
            codes = {
                client.post("/api/event", json={"event": "heatmap_open"}).status_code
                for _ in range(35)
            }
        self.assertEqual(codes, {204})
        self.assertEqual(len(self.logged_events()), 30)


class TestAdminUsage(AnalyticsFilesMixin, ChatStreamTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.use_temp_logs()

    def test_usage_summary_and_event_export(self) -> None:
        log_event("abc", "heatmap_open")
        log_event("abc", "heatmap_matrix_view")
        with self.build_client(make_settings()) as client:
            self.assertEqual(client.get("/admin/analytics/usage").status_code, 401)
            summary = client.get("/admin/analytics/usage?days=7", headers=ADMIN).json()
            exported = client.get("/admin/analytics/export?file=events", headers=ADMIN).text
            too_long = client.get("/admin/analytics/usage?days=9999", headers=ADMIN)
        self.assertEqual(summary["days"], 7)
        self.assertEqual(summary["events"]["heatmap_open"], {"count": 1, "sessions": 1})
        self.assertEqual(summary["events"]["heatmap_matrix_view"]["count"], 1)
        self.assertEqual(len(exported.splitlines()), 2)
        self.assertEqual(too_long.status_code, 422)


if __name__ == "__main__":
    unittest.main()

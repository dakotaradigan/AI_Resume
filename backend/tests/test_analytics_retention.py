"""The analytics retention window: what is pruned, what is kept, and the loop."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Prevent importing app.main from initializing an external RAG connection.
os.environ["USE_RAG"] = "false"

from analytics import analytics
from analytics.analytics import prune_analytics, prune_old_entries
from app import main as app_main

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def entry(days_ago: float, query: str) -> dict:
    return {"timestamp": (NOW - timedelta(days=days_ago)).isoformat(), "query": query}


def write_jsonl(path: Path, entries: list[dict], *, trailing: str = "") -> None:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries) + trailing, encoding="utf-8")


class TestPruneOldEntries(unittest.TestCase):
    def test_drops_only_entries_past_the_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queries.jsonl"
            write_jsonl(
                path,
                [entry(100, "old"), entry(1, "fresh"), entry(90, "on-the-cutoff")],
                trailing="not json at all\n",
            )
            self.assertEqual(prune_old_entries(path, 90, now=NOW), 1)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("old", text)
            self.assertIn("fresh", text)
            self.assertIn("on-the-cutoff", text)  # exactly the window is kept
            self.assertIn("not json at all", text)  # undated lines are kept
            self.assertEqual(len(text.splitlines()), 3)

    def test_z_suffixed_and_naive_timestamps_are_dated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queries.jsonl"
            write_jsonl(
                path,
                [
                    {"timestamp": "2026-01-25T10:30:00Z", "query": "old-z"},
                    {"timestamp": "2026-10-12T00:00:00", "query": "fresh-naive"},
                ],
            )
            self.assertEqual(prune_old_entries(path, 90, now=NOW), 1)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("old-z", text)
            self.assertIn("fresh-naive", text)

    def test_zero_days_and_missing_file_are_no_ops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queries.jsonl"
            self.assertEqual(prune_old_entries(path, 90, now=NOW), 0)
            write_jsonl(path, [entry(100, "old")])
            self.assertEqual(prune_old_entries(path, 0, now=NOW), 0)
            self.assertIn("old", path.read_text(encoding="utf-8"))


class TestPruneAnalytics(unittest.TestCase):
    def test_applies_to_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queries = Path(tmp) / "queries.jsonl"
            feedback = Path(tmp) / "feedback.jsonl"
            write_jsonl(queries, [entry(100, "a"), entry(120, "b"), entry(2, "c")])
            write_jsonl(feedback, [entry(100, "d")])
            with (
                patch.object(analytics, "ANALYTICS_FILE", queries),
                patch.object(analytics, "FEEDBACK_FILE", feedback),
                patch.object(analytics, "datetime", wraps=datetime) as clock,
            ):
                clock.now.return_value = NOW
                self.assertEqual(prune_analytics(90), {"queries": 2, "feedback": 1})


class TestRetentionLoop(unittest.TestCase):
    def test_disabled_window_never_prunes(self) -> None:
        with patch.object(app_main, "prune_analytics") as prune:
            asyncio.run(app_main._retention_loop(0))
        prune.assert_not_called()

    def test_prunes_then_sleeps_a_day(self) -> None:
        sleep = AsyncMock(side_effect=asyncio.CancelledError)
        with (
            patch.object(app_main, "prune_analytics", return_value={"queries": 1, "feedback": 0}) as prune,
            patch.object(app_main.asyncio, "sleep", sleep),
            self.assertRaises(asyncio.CancelledError),
        ):
            asyncio.run(app_main._retention_loop(90))
        prune.assert_called_once_with(90)
        sleep.assert_awaited_once_with(app_main.RETENTION_INTERVAL_SECONDS)

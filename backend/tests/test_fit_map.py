"""Tests for the Jev requirement map: line extraction, the typed request,
answer parsing, and the fit-analysis stream that carries it."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import unittest
from unittest.mock import patch

import httpx

os.environ["USE_RAG"] = "false"

from app import fit_map
from app.fit_map import (
    EVIDENCE_LEVELS,
    MAX_LINES,
    build_fit_map,
    extract_candidate_lines,
    fit_map_payload,
    parse_fit_map,
)

from tests.test_chat_stream import parse_sse, typesafe_http, typesafe_settings
from tests.test_jd_match import REALISTIC_JD, JDMatchTestCase, jd_settings


def jev_fit_answers(lines: list[str], levels: dict[int, int] | None = None,
                    not_requirements: set[int] = frozenset()) -> dict:
    """A Jev response: every line a requirement (unless excluded) scored at the
    given level (default Strong), with a peaked distribution."""
    answers: dict = {}
    for index in range(len(lines)):
        answers[f"requirement_{index}"] = {
            "type": "noul",
            "noul": 0.1 if index in not_requirements else 0.93,
        }
        level = (levels or {}).get(index, 3)
        probabilities = {str(k): 0.04 for k in range(len(EVIDENCE_LEVELS))}
        probabilities[str(level)] = 1 - 0.04 * (len(EVIDENCE_LEVELS) - 1)
        answers[f"evidence_{index}"] = {
            "type": "score",
            "score": float(level),
            "confidence": 0.8,
            "legend": {str(k): label for k, (label, _) in enumerate(EVIDENCE_LEVELS)},
            "probabilities": probabilities,
        }
    return {"model": "jev-latest", "answers": answers, "usage": {"input_tokens": 1, "output_tokens": 1}}


class TestExtractCandidateLines(unittest.TestCase):
    def test_bullets_kept_headings_dropped_order_preserved(self) -> None:
        lines = extract_candidate_lines(REALISTIC_JD)
        self.assertNotIn("Requirements:", lines)
        bullets = [
            "5+ years of product management experience",
            "Experience shipping LLM/RAG products",
            "SQL and Python fluency",
            "Strong cross-functional leadership",
        ]
        first = lines.index(bullets[0])
        self.assertEqual(lines[first:first + 4], bullets)
        # The title line is offered too; Jev decides it is not a requirement.
        self.assertEqual(lines[0], "Senior Product Manager, AI Platform")
        # Whether a surviving line is a requirement is Jev's call, so the
        # benefits sentence is still offered as a candidate.
        self.assertTrue(any("Benefits" in line for line in lines))

    def test_requirement_bullets_win_when_the_post_is_long(self) -> None:
        filler = "\n".join(f"Company fact number {i} about our offices." for i in range(40))
        post = (
            "About us\n" + filler + "\nRequirements:\n"
            "- Fluent in Python\n- Experience with vector databases\n"
        )
        lines = extract_candidate_lines(post)
        self.assertEqual(len(lines), MAX_LINES)
        self.assertIn("Fluent in Python", lines)
        self.assertIn("Experience with vector databases", lines)
        # Document order survives the ranking.
        self.assertLess(lines.index("Company fact number 0 about our offices."), lines.index("Fluent in Python"))

    def test_single_block_is_split_into_sentences(self) -> None:
        blob = (
            "We need a product manager. You have shipped machine learning features. "
            "You write SQL every week; Python is a plus."
        )
        lines = extract_candidate_lines(blob)
        self.assertEqual(
            lines,
            [
                "We need a product manager.",
                "You have shipped machine learning features.",
                "You write SQL every week;",
                "Python is a plus.",
            ],
        )

    def test_duplicates_and_short_lines_are_dropped(self) -> None:
        post = "- Python\n- Experience with FastAPI\n- experience with fastapi\n- Go"
        self.assertEqual(extract_candidate_lines(post), ["Experience with FastAPI"])


class TestFitMapPayload(unittest.TestCase):
    def test_two_typed_questions_per_line_over_one_state(self) -> None:
        lines = ["Python fluency", "Benefits include healthcare"]
        payload = fit_map_payload(lines, "RESUME TEXT", typesafe_settings())
        self.assertEqual(payload["model"], "jev-latest")
        self.assertEqual(payload["state"], {"resume": "RESUME TEXT", "job_lines": lines})
        self.assertEqual(len(payload["questions"]), 4)
        self.assertEqual(payload["questions"]["requirement_1"]["type"], "noul")
        self.assertIn("`job_lines[1]`", payload["questions"]["requirement_1"]["instructions"])
        evidence = payload["questions"]["evidence_0"]
        self.assertEqual(evidence["type"], "score")
        self.assertEqual(len(evidence["criteria"]), len(EVIDENCE_LEVELS))
        self.assertTrue(evidence["criteria"][0].startswith("Not documented"))
        self.assertIn("`resume`", evidence["instructions"])


class TestParseFitMap(unittest.TestCase):
    LINES = ["Python fluency", "Benefits include healthcare", "Led a team of ten"]

    def test_non_requirements_dropped_and_levels_resolved(self) -> None:
        body = jev_fit_answers(self.LINES, levels={0: 3, 2: 1}, not_requirements={1})
        result = parse_fit_map(self.LINES, body)
        self.assertEqual(result["levels"], [label for label, _ in EVIDENCE_LEVELS])
        self.assertEqual(result["judged"], 3)
        self.assertEqual([r["text"] for r in result["requirements"]], ["Python fluency", "Led a team of ten"])
        strong, adjacent = result["requirements"]
        self.assertEqual(strong["level"], 3)
        self.assertEqual(adjacent["level"], 1)
        self.assertEqual(len(strong["probabilities"]), len(EVIDENCE_LEVELS))
        self.assertAlmostEqual(sum(strong["probabilities"]), 1.0, places=2)
        self.assertEqual(strong["confidence"], 0.8)

    def test_too_few_requirements_is_no_map(self) -> None:
        body = jev_fit_answers(self.LINES, not_requirements={1, 2})
        self.assertIsNone(parse_fit_map(self.LINES, body))

    def test_missing_answers_are_skipped_not_fatal(self) -> None:
        body = jev_fit_answers(self.LINES)
        del body["answers"]["evidence_0"]
        result = parse_fit_map(self.LINES, body)
        self.assertEqual(
            [r["text"] for r in result["requirements"]],
            ["Benefits include healthcare", "Led a team of ten"],
        )


class TestBuildFitMap(unittest.TestCase):
    def build(self, handler):
        return asyncio.run(
            build_fit_map(REALISTIC_JD, "RESUME TEXT", typesafe_settings(), http=typesafe_http(handler))
        )

    def test_posts_the_typed_request_with_bearer_auth(self) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["auth"] = request.headers["authorization"]
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=jev_fit_answers(seen["body"]["state"]["job_lines"]))

        result = self.build(handler)
        self.assertEqual(seen["url"], "https://typesafe.test/v1/systemone")
        self.assertEqual(seen["auth"], "Bearer test-typesafe-key")
        self.assertEqual(seen["body"]["state"]["resume"], "RESUME TEXT")
        self.assertEqual(len(result["requirements"]), len(seen["body"]["state"]["job_lines"]))

    def test_http_error_yields_no_map(self) -> None:
        self.assertIsNone(self.build(lambda _: httpx.Response(500, json={"detail": "boom"})))

    def test_transport_error_yields_no_map(self) -> None:
        def handler(_request):
            raise httpx.ConnectError("down")

        self.assertIsNone(self.build(handler))

    def test_malformed_body_yields_no_map(self) -> None:
        self.assertIsNone(self.build(lambda _: httpx.Response(200, json={"answers": "nope"})))

    def test_short_descriptions_skip_the_call(self) -> None:
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={})

        result = asyncio.run(
            build_fit_map("Need a PM.", "RESUME", typesafe_settings(), http=typesafe_http(handler))
        )
        self.assertIsNone(result)
        self.assertEqual(calls, [])


class TestFitMapInAnalysisStream(JDMatchTestCase):
    """The fit-analysis stream carries the map when Jev is configured."""

    def jev_settings(self, **overrides):
        return dataclasses.replace(
            jd_settings(**overrides),
            typesafe_api_key="test-typesafe-key",
            typesafe_base_url="https://typesafe.test",
        )

    def with_jev(self, handler):
        return patch.object(fit_map, "typesafe_http_client", return_value=typesafe_http(handler))

    def test_map_event_precedes_done(self) -> None:
        def handler(request):
            lines = json.loads(request.content)["state"]["job_lines"]
            return httpx.Response(200, json=jev_fit_answers(lines, levels={0: 3, 1: 2}))

        with self.with_jev(handler), self.build_client(self.jev_settings()) as client:
            response = self.run_jd(client, REALISTIC_JD, "s1")
        self.assertEqual(response.status_code, 200)
        events = parse_sse(response.text)
        names = [name for name, _ in events]
        self.assertIn("fitmap", names)
        self.assertLess(names.index("fitmap"), names.index("done"))
        payload = dict(events)["fitmap"]
        by_text = {item["text"]: item for item in payload["requirements"]}
        self.assertIn("5+ years of product management experience", by_text)
        self.assertEqual(payload["levels"][-1], "Strong")
        # The stub scored the first two candidate lines Strong and Partial.
        self.assertEqual([item["level"] for item in payload["requirements"][:2]], [3, 2])
        self.assertEqual(len(payload["requirements"][0]["probabilities"]), 4)

    def test_no_map_without_a_typesafe_key(self) -> None:
        with self.build_client(jd_settings()) as client:
            response = self.run_jd(client, REALISTIC_JD, "s1")
        names = [name for name, _ in parse_sse(response.text)]
        self.assertNotIn("fitmap", names)
        self.assertIn("done", names)

    def test_jev_failure_leaves_the_analysis_intact(self) -> None:
        with self.with_jev(lambda _: httpx.Response(503)), self.build_client(self.jev_settings()) as client:
            response = self.run_jd(client, REALISTIC_JD, "s1")
        names = [name for name, _ in parse_sse(response.text)]
        self.assertNotIn("fitmap", names)
        self.assertEqual(names[-1], "done")

    def test_brief_mode_never_builds_a_map(self) -> None:
        calls = []

        def handler(request):
            calls.append(request)
            lines = json.loads(request.content)["state"]["job_lines"]
            return httpx.Response(200, json=jev_fit_answers(lines))

        with self.with_jev(handler), self.build_client(self.jev_settings()) as client:
            self.assertEqual(self.run_jd(client, REALISTIC_JD, "s1").status_code, 200)
            self.assertEqual(len(calls), 1)
            brief = self.run_jd(client, "brief", "s1", mode="brief")
        self.assertEqual(len(calls), 1)
        names = [name for name, _ in parse_sse(brief.text)]
        self.assertNotIn("fitmap", names)


if __name__ == "__main__":
    unittest.main()

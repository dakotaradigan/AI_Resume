"""Tests for the requirement matrix: the résumé cut into columns, the typed
request, answer parsing, and how the matrix joins the requirement map."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import unittest
from pathlib import Path

import httpx

os.environ["USE_RAG"] = "false"

from app.fit_map import build_fit_map, select_candidate_lines, split_document_lines
from app.fit_matrix import (
    MATRIX_COLUMNS,
    PART_EVIDENCE_LEVELS,
    fit_matrix_payload,
    parse_fit_matrix,
    resume_parts,
)

from tests import test_fit_map as fit_map_tests
from tests.test_chat_stream import parse_sse, typesafe_http, typesafe_settings
from tests.test_fit_map import jev_fit_answers
from tests.test_jd_match import REALISTIC_JD

REAL_RESUME = json.loads(
    (Path(__file__).resolve().parents[2] / "data" / "resume.json").read_text(encoding="utf-8")
)

SMALL_RESUME = {
    "experience": [
        {"role": "Lead PM", "company": "Acme", "duration": "2024 - Present",
         "achievements": ["Shipped a RAG product"], "technologies": ["Python"]},
        {"role": "Analyst", "company": "Acme", "duration": "2020 - 2024",
         "achievements": ["Built SQL dashboards"]},
    ],
    "projects": [{"name": "Side project", "tagline": "A chatbot", "highlights": ["FastAPI"]}],
    "education": [{"degree": "MBA", "school": "State", "graduation": "2021"}],
    "certifications": [{"name": "PCAP", "issuer": "Python Institute"}],
}


def jev_matrix_answers(lines: list[str], keys: list[str], level_of=lambda line, column: 0) -> dict:
    """A Jev response for the matrix request: every cell scored at
    ``level_of(line index, column index)`` with a peaked distribution."""
    answers: dict = {}
    for index in range(len(lines)):
        for column, key in enumerate(keys):
            level = level_of(index, column)
            probabilities = {str(k): 0.05 for k in range(len(PART_EVIDENCE_LEVELS))}
            probabilities[str(level)] = 0.85
            answers[f"cell_{index}_{key}"] = {
                "type": "score", "score": float(level), "confidence": 0.8,
                "probabilities": probabilities,
            }
    return {"model": "jev-latest", "answers": answers, "usage": {"input_tokens": 9, "output_tokens": 3}}


def jev_handler(calls: list | None = None, level_of=lambda line, column: column % 4,
                matrix_status: int = 200, not_requirements: set[int] = frozenset()):
    """Answers both Jev requests of one analysis, told apart by their state."""
    def handler(request: httpx.Request) -> httpx.Response:
        state = json.loads(request.content)["state"]
        if calls is not None:
            calls.append(state)
        if "resume_parts" in state:
            if matrix_status != 200:
                return httpx.Response(matrix_status)
            return httpx.Response(200, json=jev_matrix_answers(
                state["job_lines"], list(state["resume_parts"]), level_of))
        return httpx.Response(200, json=jev_fit_answers(
            state["job_lines"], not_requirements=not_requirements))
    return handler


class TestResumeParts(unittest.TestCase):
    def test_sections_land_in_their_columns(self) -> None:
        parts = {part.key: part for part in resume_parts(SMALL_RESUME)}
        self.assertEqual(list(parts), [column.key for column in MATRIX_COLUMNS])
        self.assertEqual(parts["current_role"].items, ["Lead PM (2024 - Present)"])
        self.assertIn("Shipped a RAG product", parts["current_role"].text)
        self.assertNotIn("SQL dashboards", parts["current_role"].text)
        self.assertIn("Built SQL dashboards", parts["earlier_roles"].text)
        self.assertIn("FastAPI", parts["projects"].text)
        self.assertEqual(parts["education"].items, ["MBA", "PCAP"])

    def test_an_empty_column_is_dropped(self) -> None:
        resume = {**SMALL_RESUME, "projects": []}
        self.assertNotIn("projects", [part.key for part in resume_parts(resume)])

    def test_real_resume_is_covered_exactly_once(self) -> None:
        # Guards an edit to MATRIX_COLUMNS: a role or project left out of
        # every column would silently hide its evidence from the grid.
        items = [item for part in resume_parts(REAL_RESUME) for item in part.items]
        expected = (
            len(REAL_RESUME["experience"]) + len(REAL_RESUME["projects"])
            + len(REAL_RESUME["education"]) + len(REAL_RESUME["certifications"])
        )
        self.assertEqual(len(items), expected)
        self.assertEqual(len(set(items)), expected)


class TestFitMatrixPayload(unittest.TestCase):
    def test_one_score_per_line_and_part_over_one_state(self) -> None:
        parts = resume_parts(SMALL_RESUME)
        lines = ["Python fluency", "Led a team of ten"]
        payload = fit_matrix_payload(lines, parts, typesafe_settings())
        self.assertEqual(payload["state"]["job_lines"], lines)
        self.assertEqual(list(payload["state"]["resume_parts"]), [part.key for part in parts])
        self.assertEqual(len(payload["questions"]), len(lines) * len(parts))
        question = payload["questions"]["cell_1_projects"]
        self.assertEqual(question["type"], "score")
        self.assertIn("`resume_parts.projects`", question["instructions"])
        self.assertIn("`job_lines[1]`", question["instructions"])
        self.assertEqual(len(question["criteria"]), len(PART_EVIDENCE_LEVELS))


class TestParseFitMatrix(unittest.TestCase):
    def setUp(self) -> None:
        self.parts = resume_parts(SMALL_RESUME)
        self.keys = [part.key for part in self.parts]

    def test_rows_follow_lines_and_cells_follow_columns(self) -> None:
        body = jev_matrix_answers(["a", "b"], self.keys, lambda line, column: (line + column) % 4)
        rows = parse_fit_matrix(2, self.parts, body)
        self.assertEqual([[cell["level"] for cell in row] for row in rows], [[0, 1, 2, 3], [1, 2, 3, 0]])
        self.assertAlmostEqual(sum(rows[0][0]["probabilities"]), 1.0, places=2)

    def test_a_missing_cell_means_no_matrix(self) -> None:
        body = jev_matrix_answers(["a", "b"], self.keys)
        del body["answers"]["cell_1_projects"]
        self.assertIsNone(parse_fit_matrix(2, self.parts, body))


class TestMatrixJoinsTheMap(unittest.TestCase):
    def build(self, handler, settings=None, resume=SMALL_RESUME):
        return asyncio.run(build_fit_map(
            REALISTIC_JD, "RESUME TEXT", settings or typesafe_settings(),
            http=typesafe_http(handler), resume=resume,
        ))

    def test_each_requirement_carries_its_own_row(self) -> None:
        # Candidate 0 is dropped as a non-requirement, so the kept
        # requirements must skip its matrix row, not shift onto it.
        calls: list = []
        result = self.build(jev_handler(
            calls, level_of=lambda line, column: line % 4, not_requirements={0}))
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [column["label"] for column in result["columns"]],
            [column.label for column in MATRIX_COLUMNS],
        )
        self.assertEqual(result["columns"][0]["items"], ["Lead PM (2024 - Present)"])
        candidates = calls[0]["job_lines"]
        for requirement in result["requirements"]:
            row = candidates.index(requirement["text"])
            self.assertNotEqual(row, 0)
            self.assertEqual([cell["level"] for cell in requirement["sources"]], [row % 4] * 4)

    def test_matrix_failure_leaves_the_map_intact(self) -> None:
        for handler in (
            jev_handler(matrix_status=503),
            jev_handler(matrix_status=413),
        ):
            result = self.build(handler)
            self.assertGreaterEqual(len(result["requirements"]), 2)
            self.assertNotIn("columns", result)
            self.assertNotIn("sources", result["requirements"][0])

    def test_setting_switches_the_matrix_off(self) -> None:
        calls: list = []
        settings = dataclasses.replace(typesafe_settings(), fit_matrix_enabled=False)
        result = self.build(jev_handler(calls), settings=settings)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("columns", result)

    def test_no_resume_means_no_matrix_request(self) -> None:
        calls: list = []
        self.build(jev_handler(calls), resume=None)
        self.assertEqual(len(calls), 1)


class TestMatrixInAnalysisStream(fit_map_tests.TestFitMapInAnalysisStream):
    """The fitmap event carries the matrix, built from the real résumé."""

    # The inherited stream tests already run with the matrix request
    # failing (their stub answers the map only); this adds the success path.
    def test_event_carries_columns_and_sources(self) -> None:
        with self.with_jev(jev_handler()), self.build_client(self.jev_settings()) as client:
            response = self.run_jd(client, REALISTIC_JD, "s1")
        payload = dict(parse_sse(response.text))["fitmap"]
        self.assertEqual(len(payload["columns"]), len(MATRIX_COLUMNS))
        self.assertEqual(
            [cell["level"] for cell in payload["requirements"][0]["sources"]], [0, 1, 2, 3]
        )


class TestSampleFiles(unittest.TestCase):
    """The home page's sample heat map: its role text and its saved file."""

    ROOT = Path(__file__).resolve().parents[2]

    def test_sample_role_yields_requirements(self) -> None:
        jd_text = (self.ROOT / "data" / "sample_jd.txt").read_text(encoding="utf-8")
        candidates = select_candidate_lines(split_document_lines(jd_text))
        self.assertGreaterEqual(len(candidates), 8)

    def test_saved_sample_is_empty_or_a_complete_map(self) -> None:
        # The page hides the sample link while `fitmap` is null. Once built
        # by scripts/build_sample_fitmap.py it must be a map the page can draw.
        sample = json.loads(
            (self.ROOT / "frontend" / "sample-fitmap.json").read_text(encoding="utf-8")
        )
        fit_map = sample["fitmap"]
        if fit_map is None:
            return
        self.assertTrue(sample["role"])
        self.assertGreaterEqual(len(fit_map["requirements"]), 2)
        for requirement in fit_map["requirements"]:
            self.assertTrue(fit_map["lines"][requirement["line"]].endswith(requirement["text"]))


if __name__ == "__main__":
    unittest.main()

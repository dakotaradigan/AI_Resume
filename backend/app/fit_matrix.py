"""Requirement matrix: where in the résumé the evidence for each line sits.

The requirement map (fit_map.py) asks Jev one question per line against the
whole résumé. This module asks the same graded question once per *part* of the
résumé, so the page can draw a grid: one row per requirement, one column per
part, each cell shaded by how well that part alone documents the requirement.

It is a second, separate TypeSafe request that runs beside the first. That
costs more questions (lines x columns), so it is isolated: if it is slow,
rejected or malformed, the requirement map is returned without a matrix and
nothing else changes. ``FIT_MATRIX_ENABLED=false`` switches it off.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# No retries and the same budget as the requirement map: the two requests run
# side by side, so the matrix never makes the map later than it already is.
TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True)
class MatrixColumn:
    """One column of the grid: a label and the résumé sections that feed it.

    ``experience`` is a slice over the résumé's experience list, which is
    newest first: ``slice(0, 1)`` is the current role, ``slice(1, None)``
    every earlier one. ``None`` leaves experience out of the column.
    """

    key: str
    label: str
    experience: slice | None = None
    projects: bool = False
    education: bool = False
    certifications: bool = False


# The columns of the grid, left to right. To regroup the résumé, edit this
# tuple: every experience entry, project, degree and certification should
# land in exactly one column, or the grid hides evidence. `key` names the
# state field Jev reads, so keep it a short lowercase identifier.
MATRIX_COLUMNS: tuple[MatrixColumn, ...] = (
    MatrixColumn("current_role", "Current role", experience=slice(0, 1)),
    MatrixColumn("earlier_roles", "Earlier Parametric roles", experience=slice(1, None)),
    MatrixColumn("projects", "Projects", projects=True),
    MatrixColumn("education", "Education & certs", education=True, certifications=True),
)

# The four levels match fit_map.EVIDENCE_LEVELS in order and label, reworded
# for one part of the résumé: a part that is silent is the normal case here.
PART_EVIDENCE_LEVELS: tuple[tuple[str, str], ...] = (
    ("Not documented", "This part of the résumé says nothing relevant to this requirement."),
    (
        "Adjacent",
        "This part shows related experience (a neighbouring skill, domain, or "
        "tool), but not this requirement itself.",
    ),
    (
        "Partial",
        "This part meets the requirement in part, in a different setting, or at "
        "a smaller scale than the posting asks for.",
    ),
    ("Strong", "This part gives clear, direct evidence that this requirement is met."),
)


@dataclass(frozen=True)
class ResumePart:
    """A column with its content: the text Jev judges and the names of the
    roles, projects or credentials it covers (shown when a cell is opened)."""

    key: str
    label: str
    items: list[str]
    text: str


def _experience_block(entry: dict) -> tuple[str, str]:
    role = entry.get("role", "")
    title = f"{role} ({entry.get('duration', '')})".strip()
    lines = [f"{role} at {entry.get('company', '')} ({entry.get('duration', '')})"]
    if entry.get("description"):
        lines.append(entry["description"])
    lines += [f"- {item}" for item in entry.get("achievements") or []]
    if entry.get("technologies"):
        lines.append(f"Technologies: {', '.join(entry['technologies'])}")
    return title, "\n".join(lines)


def _project_block(entry: dict) -> tuple[str, str]:
    name = entry.get("name", "")
    lines = [f"{name}: {entry.get('tagline', '')}".rstrip(": ")]
    for field in ("description", "problem_solved", "impact"):
        if entry.get(field):
            lines.append(str(entry[field]))
    lines += [f"- {item}" for item in entry.get("highlights") or []]
    if entry.get("tech_stack"):
        lines.append(f"Tech stack: {', '.join(entry['tech_stack'])}")
    return name, "\n".join(lines)


def _education_block(entry: dict) -> tuple[str, str]:
    parts = [entry.get("degree", ""), entry.get("school", ""), entry.get("graduation", "")]
    return entry.get("degree", ""), ", ".join(part for part in parts if part)


def _certification_block(entry: dict) -> tuple[str, str]:
    parts = [entry.get("name", ""), entry.get("issuer", ""), entry.get("date", "")]
    return entry.get("name", ""), " - ".join(part for part in parts if part)


def resume_parts(
    resume: dict, columns: tuple[MatrixColumn, ...] = MATRIX_COLUMNS
) -> list[ResumePart]:
    """The résumé cut into the grid's columns. A column with no content (a
    résumé with no projects, say) is dropped rather than judged empty."""
    parts: list[ResumePart] = []
    for column in columns:
        blocks: list[tuple[str, str]] = []
        if column.experience is not None:
            blocks += [_experience_block(e) for e in (resume.get("experience") or [])[column.experience]]
        if column.projects:
            blocks += [_project_block(p) for p in resume.get("projects") or []]
        if column.education:
            blocks += [_education_block(e) for e in resume.get("education") or []]
        if column.certifications:
            blocks += [_certification_block(c) for c in resume.get("certifications") or []]
        blocks = [(title, text) for title, text in blocks if text.strip()]
        if not blocks:
            continue
        parts.append(ResumePart(
            key=column.key,
            label=column.label,
            items=[title for title, _ in blocks if title],
            text="\n\n".join(text for _, text in blocks),
        ))
    return parts


def fit_matrix_payload(
    lines: list[str], parts: list[ResumePart], settings: Settings
) -> dict[str, Any]:
    """Request body for /v1/systemone: one Score per (line, résumé part) over
    one state. Each instruction names both state fields it judges."""
    questions: dict[str, Any] = {}
    for index in range(len(lines)):
        for part in parts:
            questions[f"cell_{index}_{part.key}"] = {
                "type": "score",
                "instructions": (
                    f"`resume_parts.{part.key}` is one part of the candidate's résumé "
                    f"({part.label}). `job_lines[{index}]` is a requirement from a job "
                    "posting. Rate how well this part of the résumé, on its own, "
                    "documents that the candidate meets the requirement. Judge only "
                    "what this part states; do not assume unstated skills or "
                    "experience, and ignore the rest of the résumé."
                ),
                "criteria": [
                    f"{label}: {description}" for label, description in PART_EVIDENCE_LEVELS
                ],
            }
    return {
        "state": {
            "resume_parts": {part.key: part.text for part in parts},
            "job_lines": lines,
        },
        "model": settings.typesafe_model,
        "questions": questions,
    }


def parse_fit_matrix(
    line_count: int, parts: list[ResumePart], body: dict[str, Any]
) -> list[list[dict[str, Any]]] | None:
    """Jev's answers as one row of cells per line, in column order. Each cell
    carries the most likely level and the full distribution. Returns None
    when any cell is missing: a grid with holes would read as "no evidence"."""
    answers = body.get("answers") or {}
    level_count = len(PART_EVIDENCE_LEVELS)
    rows: list[list[dict[str, Any]]] = []
    for index in range(line_count):
        row: list[dict[str, Any]] = []
        for part in parts:
            raw = (answers.get(f"cell_{index}_{part.key}") or {}).get("probabilities") or {}
            probabilities = [float(raw.get(str(level), 0.0)) for level in range(level_count)]
            if not any(probabilities):
                return None
            row.append({
                "level": max(range(level_count), key=probabilities.__getitem__),
                "probabilities": [round(p, 3) for p in probabilities],
            })
        rows.append(row)
    return rows


async def build_fit_matrix(
    lines: list[str],
    resume: dict,
    settings: Settings,
    client: httpx.AsyncClient,
) -> dict[str, Any] | None:
    """Ask Jev for the grid. Returns ``{"columns": [...], "rows": [...]}``
    with one row of cells per entry of ``lines``, or None on any failure;
    never raises, so the requirement map can run beside it unguarded."""
    parts = resume_parts(resume)
    if len(parts) < 2 or not lines:
        return None
    try:
        response = await client.post(
            f"{settings.typesafe_base_url.rstrip('/')}/v1/systemone",
            json=fit_matrix_payload(lines, parts, settings),
            headers={"Authorization": f"Bearer {settings.typesafe_api_key}"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Jev requirement matrix failed; the map continues without it")
        return None
    try:
        rows = parse_fit_matrix(len(lines), parts, body)
        usage = body.get("usage") or {}
    except (TypeError, ValueError, AttributeError):
        rows = None
    if rows is None:
        logger.warning("Jev requirement matrix response was malformed")
        return None
    # Logged so the cost of the extra questions can be read off production.
    logger.info(
        "Jev requirement matrix: %d lines x %d columns, input_tokens=%s output_tokens=%s",
        len(lines), len(parts), usage.get("input_tokens"), usage.get("output_tokens"),
    )
    return {
        "columns": [{"label": part.label, "items": part.items} for part in parts],
        "rows": rows,
    }

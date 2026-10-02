"""Requirement map: Jev scores each line of a pasted job description against
the résumé in one typed pass.

The fit analysis is Claude's prose. This module adds structured data beside
it: for every candidate line of the job description, one yes/no judgment
("is this a requirement?") and one ordered rating ("how well does the résumé
document it?"), all asked in a single TypeSafe request so they run in parallel
with the prose and add no latency. The answers are probabilities, not text, so
the page can re-weight and re-sort them (must-haves first, evidence order)
without asking the model again.

The map is best-effort: any failure here leaves the analysis untouched.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from app.config import Settings
from app.llm import typesafe_http_client

logger = logging.getLogger(__name__)

# Evidence levels, ordered from zero. A level's position in this tuple is its
# score, so the first entry must stay the "nothing found" outcome.
EVIDENCE_LEVELS: tuple[tuple[str, str], ...] = (
    ("Not documented", "The résumé says nothing relevant to this requirement."),
    (
        "Adjacent",
        "The résumé shows related experience (a neighbouring skill, domain, or "
        "tool), but not this requirement itself.",
    ),
    (
        "Partial",
        "The requirement is met in part, in a different setting, or at a smaller "
        "scale than the posting asks for.",
    ),
    ("Strong", "The résumé gives clear, direct evidence that this requirement is met."),
)

# Each candidate line costs two questions; twenty lines keeps one request
# comfortably small while covering the requirement sections of a typical post.
MAX_LINES = 20
MIN_REQUIREMENTS = 2
MIN_LINE_CHARS = 12
MAX_LINE_CHARS = 280
# A Noul near 0.5 is a coin flip; keep a line only when Jev leans "requirement".
REQUIREMENT_MIN_PROBABILITY = 0.5
# One request carries up to forty questions, so it gets more room than the
# router's two seconds. No retries: the map is optional.
TIMEOUT_SECONDS = 8.0

_BULLET_RE = re.compile(r"^\s*(?:[-•*·–—▪●◦]+|\d{1,2}[.)])\s+")
# Heading phrases are matched at the start of a short line only, so a short
# requirement that merely contains one ("Strong SQL skills") stays content.
_REQUIREMENT_HEADING_RE = re.compile(
    r"^(?:key |core |basic |minimum |required |preferred |desired |your |the )?"
    r"(?:requirement|qualification|what you|you (?:have|bring|are)|must.have|"
    r"nice.to.have|preferred|skills|experience|looking for|about you|who you are|"
    r"responsibilit)",
    re.IGNORECASE,
)
_OTHER_HEADING_RE = re.compile(
    r"^(?:benefit|perk|compensation|salary|about (?:us|the company|the team|the role)|"
    r"equal opportunity|how to apply|what we offer|our mission|why join)",
    re.IGNORECASE,
)


def _normalize(line: str) -> str:
    return " ".join(line.split())


def _is_heading(line: str) -> bool:
    """A section label, not content: short, ends with a colon, or reads like
    one of the headings job posts use. A sentence is never a heading, however
    much it sounds like one ("You have shipped ML features.")."""
    if line[-1] in ".!?;" or _BULLET_RE.match(line):
        return False
    words = len(line.split())
    if line.endswith(":") and words <= 8:
        return True
    return words <= 3 and bool(
        _REQUIREMENT_HEADING_RE.match(line) or _OTHER_HEADING_RE.match(line)
    )


def extract_candidate_lines(jd_text: str, limit: int = MAX_LINES) -> list[str]:
    """The lines of a job description worth judging, in document order.

    Bullets under a requirements-style heading come first when the post is
    longer than the limit, then other bullets, then plain lines. Headings are
    dropped; whether a surviving line is really a requirement is Jev's call.
    A post pasted as one block is split into sentences instead.
    """
    raw_lines = [_normalize(line) for line in jd_text.splitlines()]
    raw_lines = [line for line in raw_lines if line]
    if len(raw_lines) < 3:
        raw_lines = [
            _normalize(part) for part in re.split(r"(?<=[.;!?])\s+", " ".join(raw_lines))
        ]

    ranked: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    in_requirements = False
    for index, line in enumerate(raw_lines):
        if _is_heading(line):
            if _OTHER_HEADING_RE.match(line):
                in_requirements = False
            elif _REQUIREMENT_HEADING_RE.match(line):
                in_requirements = True
            continue
        bulleted = bool(_BULLET_RE.match(line))
        text = _BULLET_RE.sub("", line).strip()
        if not MIN_LINE_CHARS <= len(text) <= MAX_LINE_CHARS:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        priority = (0 if in_requirements else 2) + (0 if bulleted else 1)
        ranked.append((priority, index, text))

    ranked.sort()
    kept = sorted(ranked[:limit], key=lambda item: item[1])
    return [text for _, _, text in kept]


def fit_map_payload(lines: list[str], resume_context: str, settings: Settings) -> dict[str, Any]:
    """Request body for TypeSafe's /v1/systemone endpoint: one state, two
    questions per line. Question ids are for code only; each instruction names
    the state field it judges, as the TypeSafe guidance asks."""
    questions: dict[str, Any] = {}
    for index in range(len(lines)):
        ref = f"`job_lines[{index}]`"
        questions[f"requirement_{index}"] = {
            "type": "noul",
            "instructions": (
                f"{ref} is one line from a job posting. Decide whether it states a "
                "requirement, qualification, or responsibility the candidate should meet."
            ),
            "criteria": {
                "true": (
                    "A skill, experience level, credential, domain knowledge, or "
                    "responsibility the candidate is expected to have or do."
                ),
                "false": (
                    "Compensation, benefits, company or team description, "
                    "equal-opportunity text, logistics, a heading, or an application "
                    "instruction."
                ),
            },
        }
        questions[f"evidence_{index}"] = {
            "type": "score",
            "instructions": (
                f"`resume` is the candidate's résumé. {ref} is a requirement from a "
                "job posting. Rate how well the résumé documents that the candidate "
                "meets it. Judge only what the résumé states; do not assume unstated "
                "skills or experience."
            ),
            "criteria": [f"{label}: {description}" for label, description in EVIDENCE_LEVELS],
        }
    return {
        "state": {"resume": resume_context, "job_lines": lines},
        "model": settings.typesafe_model,
        "questions": questions,
    }


def parse_fit_map(lines: list[str], body: dict[str, Any]) -> dict[str, Any] | None:
    """Turn Jev's answers into the map the page renders.

    Lines Jev does not consider requirements are dropped. Each kept line
    carries the full probability distribution over the evidence levels (the
    page draws it) and the most likely level (the page labels it). Returns
    None when fewer than MIN_REQUIREMENTS lines survive.
    """
    answers = body.get("answers") or {}
    level_count = len(EVIDENCE_LEVELS)
    requirements: list[dict[str, Any]] = []
    for index, text in enumerate(lines):
        is_requirement = answers.get(f"requirement_{index}") or {}
        evidence = answers.get(f"evidence_{index}") or {}
        p_requirement = float(is_requirement.get("noul", 0.0))
        if p_requirement < REQUIREMENT_MIN_PROBABILITY:
            continue
        raw = evidence.get("probabilities") or {}
        probabilities = [float(raw.get(str(level), 0.0)) for level in range(level_count)]
        if not any(probabilities):
            continue
        level = max(range(level_count), key=probabilities.__getitem__)
        requirements.append({
            "text": text,
            "level": level,
            "probabilities": [round(p, 3) for p in probabilities],
            "expected": round(float(evidence.get("score", level)), 2),
            "confidence": round(float(evidence.get("confidence", 0.0)), 2),
            "requirement_probability": round(p_requirement, 2),
        })
    if len(requirements) < MIN_REQUIREMENTS:
        return None
    return {
        "levels": [label for label, _ in EVIDENCE_LEVELS],
        "requirements": requirements,
        "model": str(body.get("model") or ""),
        "judged": len(lines),
    }


async def build_fit_map(
    jd_text: str,
    resume_context: str,
    settings: Settings,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any] | None:
    """Ask Jev for the map. Returns None on any failure; never raises, so the
    caller can run it alongside the prose stream without guarding it."""
    lines = extract_candidate_lines(jd_text)
    if len(lines) < MIN_REQUIREMENTS:
        return None
    client = http or typesafe_http_client()
    try:
        response = await client.post(
            f"{settings.typesafe_base_url.rstrip('/')}/v1/systemone",
            json=fit_map_payload(lines, resume_context, settings),
            headers={"Authorization": f"Bearer {settings.typesafe_api_key}"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Jev requirement map failed; the analysis continues without it")
        return None
    try:
        fit_map = parse_fit_map(lines, body)
    except (TypeError, ValueError, AttributeError):
        logger.warning("Jev requirement map response was malformed")
        return None
    if fit_map:
        logger.info(
            "Jev requirement map: %d of %d lines kept", len(fit_map["requirements"]), len(lines)
        )
    return fit_map

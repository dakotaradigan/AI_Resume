"""Prompt and resume content loading (cached until explicitly cleared)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.constants import SITE_URL


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"File not found: {path}") from exc
    except OSError as exc:
        raise RuntimeError(f"Unable to read file: {path}") from exc


def _format_resume_context(data: dict) -> str:
    lines: list[str] = []
    personal = data.get("personal", {})
    if personal:
        name = personal.get("name", "").strip()
        title = personal.get("title", "").strip()
        summary = personal.get("summary", "").strip()
        header = " - ".join([part for part in [name, title] if part])
        if header:
            lines.append(header)
        if summary:
            lines.append(summary)

    about = data.get("about", {})
    if about:
        lines.append("About Dakota (working style, values, interests):")
        for item in about.get("working_style", []):
            lines.append(f"- {item}")
        for item in about.get("values", []):
            lines.append(f"- Values: {item}")
        interests = about.get("interests", [])
        if interests:
            lines.append(f"- Interests: {'; '.join(interests)}")
        if about.get("path_into_product"):
            lines.append(f"- Path into product: {about['path_into_product']}")
        if about.get("what_energizes"):
            lines.append(f"- What energizes him: {about['what_energizes']}")

    experiences = data.get("experience", [])
    if experiences:
        lines.append("Experience:")
        for exp in experiences:
            role = exp.get("role", "")
            company = exp.get("company", "")
            duration = exp.get("duration", "")
            achievements = exp.get("achievements", []) or []
            sample_achievements = "; ".join(achievements[:3])
            lines.append(
                f"- {role} at {company} ({duration}) — {sample_achievements}".strip()
            )

    projects = data.get("projects", [])
    if projects:
        lines.append("Projects:")
        for proj in projects:
            name = proj.get("name", "")
            tagline = proj.get("tagline", "")
            highlights = "; ".join((proj.get("highlights") or [])[:2])
            lines.append(
                f"- {name}: {tagline}".strip()
                + (f" — {highlights}" if highlights else "")
            )

    skills = data.get("skills", {})
    if skills:
        lines.append("Skills:")
        for category, items in skills.items():
            if items:
                category_name = category.replace("_", " ").title()
                lines.append(f"- {category_name}: {', '.join(items)}")

    education = data.get("education", [])
    if education:
        lines.append("Education:")
        for edu in education:
            degree = edu.get("degree", "")
            school = edu.get("school", "")
            graduation = edu.get("graduation", "")
            edu_parts = [p for p in [degree, school, graduation] if p]
            if edu_parts:
                lines.append(f"- {', '.join(edu_parts)}")

    certifications = data.get("certifications", [])
    if certifications:
        lines.append("Certifications:")
        # Include top 5 most recent/relevant certifications
        for cert in certifications[:5]:
            name = cert.get("name", "")
            issuer = cert.get("issuer", "")
            date = cert.get("date", "")
            cert_parts = [p for p in [name, issuer, date] if p]
            if cert_parts:
                lines.append(f"- {' - '.join(cert_parts)}")

    return "\n".join(lines)


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    settings = get_settings()
    return _read_text(settings.data_dir / "system_prompt.txt").strip()


@lru_cache(maxsize=1)
def load_jd_match_prompt() -> str:
    settings = get_settings()
    return _read_text(settings.data_dir / "jd_match_prompt.txt").strip()


def _load_resume_json() -> dict:
    settings = get_settings()
    resume_path = settings.data_dir / "resume.json"
    try:
        return json.loads(resume_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Resume data not found: {resume_path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Resume data is not valid JSON: {resume_path}") from exc
    except OSError as exc:
        raise RuntimeError(f"Unable to read resume data: {resume_path}") from exc


@lru_cache(maxsize=1)
def load_resume_context() -> str:
    """
    Static context for the model (fallback when RAG is disabled or degraded).
    """
    return _format_resume_context(_load_resume_json())


@lru_cache(maxsize=1)
def load_resume_json_public() -> dict:
    """
    Public resume payload for the frontend UI.
    Intentionally excludes phone number.
    """
    data = _load_resume_json()
    personal = dict(data.get("personal", {}) or {})
    personal.pop("phone", None)
    data["personal"] = personal
    return data


@lru_cache(maxsize=1)
def render_llms_text() -> str:
    """Markdown digest of the resume for LLM crawlers (llms.txt convention).

    Rendered from the same phone-scrubbed payload as /api/resume so it can
    never drift from the source of truth.
    """
    data = load_resume_json_public()
    personal = data.get("personal", {})
    lines: list[str] = [
        f"# {personal.get('name', 'Dakota Radigan')} — {personal.get('title', '')}".rstrip(" —"),
        "",
        f"> {personal.get('summary', '').strip()}",
        "",
        f"- Site (chat with an AI assistant about this resume): {SITE_URL}",
        f"- Resume as JSON: {SITE_URL}/api/resume",
        f"- MCP endpoint (streamable HTTP, one tool: get_resume): {SITE_URL}/mcp",
        f"- Email: {personal.get('email', '')}",
        f"- LinkedIn: {personal.get('linkedin', '')}",
        f"- Location: {personal.get('location', '')}",
        "",
        "## Experience",
    ]
    for job in data.get("experience", []):
        lines.append(
            f"### {job.get('role', '')} — {job.get('company', '')} ({job.get('duration', '')})"
        )
        if job.get("description"):
            lines.append(job["description"].strip())
        for achievement in (job.get("achievements") or [])[:3]:
            lines.append(f"- {achievement}")
        lines.append("")
    lines.append("## Projects")
    for project in data.get("projects", []):
        lines.append(f"### {project.get('name', '')} — {project.get('tagline', '')}")
        if project.get("impact"):
            lines.append(f"- Impact: {project['impact']}")
        if project.get("tech_stack"):
            lines.append(f"- Stack: {', '.join(project['tech_stack'])}")
        lines.append("")
    lines.append("## Skills")
    for category, items in (data.get("skills") or {}).items():
        label = category.replace("_", " ").title()
        lines.append(f"- {label}: {', '.join(items)}")
    lines.append("")
    about = data.get("about", {})
    if about:
        lines.append("## About Dakota")
        for item in about.get("working_style", []):
            lines.append(f"- {item}")
        for item in about.get("values", []):
            lines.append(f"- Values: {item}")
        if about.get("interests"):
            lines.append(f"- Interests: {'; '.join(about['interests'])}")
        if about.get("path_into_product"):
            lines.append(f"- Path into product: {about['path_into_product']}")
        if about.get("what_energizes"):
            lines.append(f"- What energizes him: {about['what_energizes']}")
        lines.append("")
    lines.append("## Certifications")
    for cert in data.get("certifications", []):
        entry = f"- {cert.get('name', '')} — {cert.get('issuer', '')}"
        if cert.get("date"):
            entry += f" ({cert['date']})"
        lines.append(entry)
    lines.append("")
    return "\n".join(lines)


def clear_caches() -> None:
    """Drop all cached content so the next request re-reads the data files."""
    load_system_prompt.cache_clear()
    load_jd_match_prompt.cache_clear()
    load_resume_context.cache_clear()
    load_resume_json_public.cache_clear()
    render_llms_text.cache_clear()

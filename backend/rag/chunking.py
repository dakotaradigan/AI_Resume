"""Chunk resume JSON and project markdown into retrieval units."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """Represents a chunk of resume or project source data with metadata."""

    text: str
    chunk_type: str  # e.g. personal, experience, project, project_doc, skills
    title: str
    timeframe: str | None = None
    tags: list[str] | None = None


def chunk_resume_data(resume_path: Path) -> list[DocumentChunk]:
    """
    Chunk resume JSON into semantic units.

    Strategy:
    - Personal info: 1 chunk
    - About (working style, values, interests): 1 chunk
    - Each job experience: 1 chunk (with all achievements)
    - Each project: 1-3 chunks depending on detail
    - Skills: 1 chunk
    - Education: 1 chunk
    - Certifications: 1 chunk
    """
    with open(resume_path, encoding="utf-8") as f:
        data = json.load(f)

    chunks: list[DocumentChunk] = []

    # Personal info chunk
    personal = data.get("personal", {})
    if personal:
        text_parts = [
            f"Name: {personal.get('name', '')}",
            f"Title: {personal.get('title', '')}",
            f"Location: {personal.get('location', '')}",
            f"Summary: {personal.get('summary', '')}",
            f"Email: {personal.get('email', '')}",
            f"LinkedIn: {personal.get('linkedin', '')}",
            # Phone intentionally excluded - PII should not be in RAG context
        ]
        text = "\n".join([p for p in text_parts if p and not p.endswith(": ")])
        chunks.append(
            DocumentChunk(
                text=text,
                chunk_type="personal",
                title="Personal Information",
                tags=["contact", "summary"],
            )
        )

    # About chunk (working style, values, interests)
    about = data.get("about", {})
    if about:
        about_parts: list[str] = []

        working_style = about.get("working_style", [])
        if working_style:
            about_parts.append("How Dakota likes to work:")
            about_parts.extend(f"- {item}" for item in working_style)
            about_parts.append("")

        values = about.get("values", [])
        if values:
            about_parts.append("What Dakota values in work and teams:")
            about_parts.extend(f"- {item}" for item in values)
            about_parts.append("")

        interests = about.get("interests", [])
        if interests:
            about_parts.append("Hobbies and interests outside of work:")
            about_parts.extend(f"- {item}" for item in interests)
            about_parts.append("")

        path = about.get("path_into_product", "")
        if path:
            about_parts.append(f"How Dakota got into product and AI: {path}")
            about_parts.append("")

        energizes = about.get("what_energizes", "")
        if energizes:
            about_parts.append(f"What energizes Dakota: {energizes}")

        if about_parts:
            chunks.append(
                DocumentChunk(
                    text="\n".join(about_parts).strip(),
                    chunk_type="about",
                    title="About Dakota — Working Style, Values, and Interests",
                    tags=[
                        "about",
                        "personality",
                        "working style",
                        "values",
                        "hobbies",
                        "interests",
                        "culture fit",
                    ],
                )
            )

    # Experience chunks (one per job)
    for exp in data.get("experience", []):
        achievements = exp.get("achievements", [])
        achievements_text = "\n".join([f"- {a}" for a in achievements])
        text = f"""
Role: {exp.get('role', '')}
Company: {exp.get('company', '')}
Duration: {exp.get('duration', '')}
Description: {exp.get('description', '')}

Achievements:
{achievements_text}

Technologies: {', '.join(exp.get('technologies', []))}
        """.strip()

        chunks.append(
            DocumentChunk(
                text=text,
                chunk_type="experience",
                title=f"{exp.get('role', '')} at {exp.get('company', '')}",
                timeframe=exp.get("duration", ""),
                tags=exp.get("technologies", []),
            )
        )

    # Project chunks
    for proj in data.get("projects", []):
        # Main project chunk (overview)
        highlights = proj.get("highlights", [])
        highlights_text = "\n".join([f"- {h}" for h in highlights])

        # Add distinguishing context early in the chunk
        main_text = f"""
Project: {proj.get('name', '')}
Context: {proj.get('context', '')}
Timeframe: {proj.get('timeframe', '')}
Tagline: {proj.get('tagline', '')}

Description:
{proj.get('description', '')}

Key Highlights:
{highlights_text}

Problem Solved:
{proj.get('problem_solved', '')}

Impact:
{proj.get('impact', '')}

Tech Stack: {', '.join(proj.get('tech_stack', []))}
        """.strip()

        chunks.append(
            DocumentChunk(
                text=main_text,
                chunk_type="project",
                title=proj.get("name", ""),
                timeframe=proj.get("timeframe", ""),
                tags=proj.get("tech_stack", []),
            )
        )

        # Architecture details chunk (if present)
        arch_details = proj.get("architecture_details")
        if arch_details:
            # Add distinguishing context at the beginning
            arch_text_parts = [
                f"Project: {proj.get('name', '')} - Architecture Details",
                f"Context: {proj.get('context', '')}",
                f"Timeframe: {proj.get('timeframe', '')}",
                "",
                f"Frontend: {arch_details.get('frontend', '')}",
                f"Backend: {arch_details.get('backend', '')}",
                f"AI Orchestration: {arch_details.get('ai_orchestration', '')}",
                f"Data Layer: {arch_details.get('data_layer', '')}",
                "",
                "Core Capabilities:",
            ]
            for cap in arch_details.get("core_capabilities", []):
                arch_text_parts.append(f"- {cap}")

            chunks.append(
                DocumentChunk(
                    text="\n".join(arch_text_parts),
                    chunk_type="project",
                    title=f"{proj.get('name', '')} - Architecture",
                    timeframe=proj.get("timeframe", ""),
                    tags=["architecture"] + proj.get("tech_stack", []),
                )
            )

    # Skills chunk
    skills = data.get("skills", {})
    if skills:
        skills_parts = []
        for category, skill_list in skills.items():
            skills_parts.append(f"{category.replace('_', ' ').title()}:")
            skills_parts.append(", ".join(skill_list))
            skills_parts.append("")

        chunks.append(
            DocumentChunk(
                text="\n".join(skills_parts).strip(),
                chunk_type="skills",
                title="Skills and Expertise",
                tags=["skills", "technical", "leadership"],
            )
        )

    # Education chunk
    education = data.get("education", [])
    if education:
        edu_parts = []
        for edu in education:
            edu_lines = [
                f"Degree: {edu.get('degree', '')}",
                f"School: {edu.get('school', '')}",
                f"Graduated: {edu.get('graduation', '')}",
            ]
            # Filter out empty values (matches personal chunk pattern)
            edu_text = "\n".join([line for line in edu_lines if line and not line.endswith(": ")])
            if edu_text:
                edu_parts.append(edu_text)
                edu_parts.append("")  # Spacing between degrees

        if edu_parts:
            chunks.append(
                DocumentChunk(
                    text="\n".join(edu_parts).strip(),
                    chunk_type="education",
                    title="Education",
                    tags=["education", "academic"],
                )
            )

    # Certifications chunk
    certifications = data.get("certifications", [])
    if certifications:
        cert_parts = []
        for cert in certifications:
            name = cert.get("name", "").strip()
            issuer = cert.get("issuer", "").strip()
            status = cert.get("status", "").strip()

            # Build cert line only if we have name or issuer
            if name or issuer:
                cert_line = " - ".join([p for p in [name, issuer] if p])
                if status:
                    cert_line += f" ({status})"
                cert_parts.append(cert_line)

        if cert_parts:
            chunks.append(
                DocumentChunk(
                    text="\n".join(cert_parts).strip(),
                    chunk_type="certifications",
                    title="Certifications",
                    tags=["certifications", "credentials"],
                )
            )

    logger.info(f"Created {len(chunks)} document chunks")
    return chunks


def chunk_project_docs(projects_dir: Path) -> list[DocumentChunk]:
    """Chunk project markdown files by H2 section."""
    chunks: list[DocumentChunk] = []

    for project_path in sorted(projects_dir.glob("*.md")):
        markdown = project_path.read_text(encoding="utf-8")
        title_match = re.search(r"^#\s+(.+?)\s*$", markdown, re.MULTILINE)
        if title_match is None:
            logger.warning(f"Skipping project doc without H1 title: {project_path}")
            continue
        document_title = title_match.group(1).strip()

        sections = re.split(r"^##\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
        for index in range(1, len(sections), 2):
            section_heading = sections[index].strip()
            section_body = sections[index + 1].strip()
            section_text = f"## {section_heading}\n\n{section_body}".strip()

            if len(section_body) < 300 and chunks and chunks[-1].title.startswith(
                f"{document_title} — "
            ):
                chunks[-1].text = f"{chunks[-1].text}\n\n{section_text}"
                continue

            chunks.append(
                DocumentChunk(
                    text=f"# {document_title}\n\n{section_text}",
                    chunk_type="project_doc",
                    title=f"{document_title} — {section_heading}",
                )
            )

    logger.info(f"Created {len(chunks)} project document chunks")
    return chunks


def build_corpus(resume_path: Path, projects_dir: Path | None) -> list[DocumentChunk]:
    """Build the complete resume and project-document corpus."""
    chunks = chunk_resume_data(resume_path)
    if projects_dir is not None and projects_dir.is_dir():
        chunks.extend(chunk_project_docs(projects_dir))
    logger.info(f"Built corpus with {len(chunks)} chunks")
    return chunks

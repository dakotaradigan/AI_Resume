"""Resume PDF rendering (password-gated download)."""

from __future__ import annotations

import io
from functools import lru_cache
from typing import Any

from app.constants import SITE_URL
from app.content import load_resume_json_public

# PDF palette: print-friendly values of the site's light-theme tokens.
_PDF_TEXT = "#232830"
_PDF_MUTED = "#6b7280"
_PDF_ACCENT = "#b3641a"


@lru_cache(maxsize=1)
def render_resume_pdf() -> bytes:
    """Polished PDF rendered from the phone-scrubbed resume payload.

    Import is local so the app still boots if reportlab is absent in a
    stripped-down dev env; the route turns that into a 500 with a clear log.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    data = load_resume_json_public()
    personal = data.get("personal", {})

    def esc(value: Any) -> str:
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    name_style = ParagraphStyle(
        "name", fontName="Helvetica-Bold", fontSize=21, leading=25,
        textColor=colors.HexColor(_PDF_TEXT), alignment=TA_LEFT,
    )
    contact_style = ParagraphStyle(
        "contact", fontName="Helvetica", fontSize=9, leading=12,
        textColor=colors.HexColor(_PDF_MUTED),
    )
    section_style = ParagraphStyle(
        "section", fontName="Helvetica-Bold", fontSize=10.5, leading=13,
        textColor=colors.HexColor(_PDF_ACCENT), spaceBefore=10, spaceAfter=2,
    )
    role_style = ParagraphStyle(
        "role", fontName="Helvetica-Bold", fontSize=10, leading=13,
        textColor=colors.HexColor(_PDF_TEXT), spaceBefore=5,
    )
    body_style = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=9, leading=12,
        textColor=colors.HexColor(_PDF_TEXT),
    )
    bullet_style = ParagraphStyle(
        "bullet", parent=body_style, leftIndent=10, bulletIndent=2, spaceAfter=1,
    )

    story: list[Any] = [
        Paragraph(esc(personal.get("name", "")), name_style),
        Paragraph(esc(personal.get("title", "")), body_style),
        Spacer(1, 4),
        Paragraph(
            " · ".join(
                esc(part) for part in (
                    personal.get("location"), personal.get("email"),
                    personal.get("linkedin"), SITE_URL,
                ) if part
            ),
            contact_style,
        ),
        Spacer(1, 6),
    ]

    def section(title: str) -> None:
        story.append(Paragraph(title.upper(), section_style))
        story.append(
            HRFlowable(width="100%", thickness=0.7, color=colors.HexColor(_PDF_ACCENT))
        )
        story.append(Spacer(1, 3))

    if personal.get("summary"):
        section("Summary")
        story.append(Paragraph(esc(personal["summary"]), body_style))

    section("Experience")
    for job in data.get("experience", []):
        story.append(
            Paragraph(
                f"{esc(job.get('role', ''))} — {esc(job.get('company', ''))}"
                f" <font color='{_PDF_MUTED}' size='8.5'>({esc(job.get('duration', ''))})</font>",
                role_style,
            )
        )
        for achievement in (job.get("achievements") or [])[:4]:
            story.append(Paragraph(esc(achievement), bullet_style, bulletText="•"))

    section("Projects")
    for project in data.get("projects", []):
        story.append(
            Paragraph(
                f"{esc(project.get('name', ''))} — {esc(project.get('tagline', ''))}",
                role_style,
            )
        )
        detail = project.get("impact") or project.get("description") or ""
        if detail:
            story.append(Paragraph(esc(detail), bullet_style, bulletText="•"))

    section("Skills")
    for category, items in (data.get("skills") or {}).items():
        label = category.replace("_", " ").title()
        story.append(
            Paragraph(f"<b>{esc(label)}:</b> {esc(', '.join(items))}", body_style)
        )

    if data.get("education"):
        section("Education")
        for entry in data["education"]:
            story.append(
                Paragraph(
                    f"{esc(entry.get('degree', ''))} — {esc(entry.get('school', ''))}"
                    f" <font color='{_PDF_MUTED}' size='8.5'>({esc(entry.get('graduation', ''))})</font>",
                    body_style,
                )
            )

    section("Certifications")
    for cert in data.get("certifications", []):
        line = f"{esc(cert.get('name', ''))} — {esc(cert.get('issuer', ''))}"
        if cert.get("date"):
            line += f" ({esc(cert['date'])})"
        story.append(Paragraph(line, bullet_style, bulletText="•"))

    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=f"{personal.get('name', 'Resume')} — Resume",
        author=personal.get("name", ""),
    ).build(story)
    return buffer.getvalue()

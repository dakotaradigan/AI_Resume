"""Public resume data: JSON payload, llms.txt digest, gated PDF download."""

from __future__ import annotations

import asyncio
import logging

from analytics.analytics import anonymize_session_id
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from app.constants import PDF_LOCKED_MESSAGE
from app.content import load_resume_json_public, render_llms_text
from app.dependencies import app_settings
from app.identity import get_client_ip, resolve_visitor_id, set_visitor_cookie
from app.resume_pdf import render_resume_pdf
from app.session_store import get_session_store

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/resume")
async def get_resume() -> dict:
    """
    Public resume data used to render the sections below the chatbot UI.
    """
    try:
        return load_resume_json_public()
    except RuntimeError as exc:
        logger.exception("Failed to load resume JSON for frontend")
        raise HTTPException(
            status_code=500, detail="Unable to load resume data."
        ) from exc


@router.get("/llms.txt")
async def llms_txt() -> PlainTextResponse:
    """Machine-readable resume digest (llms.txt convention), rendered
    live from resume.json so it can never drift."""
    try:
        return PlainTextResponse(render_llms_text(), media_type="text/plain; charset=utf-8")
    except RuntimeError as exc:
        logger.exception("Failed to render llms.txt")
        raise HTTPException(status_code=500, detail="Unable to render llms.txt") from exc


@router.get("/api/resume.pdf")
async def resume_pdf(request: Request) -> Response:
    """Password-gated PDF download. The chat password (printed on
    Dakota's resume) unlocks the visitor identity via /api/unlock;
    unlocked visitors download a PDF rendered live from resume.json.
    Locked visitors get 403 and the frontend shows the unlock form
    (which mints the visitor cookie itself)."""
    settings = app_settings(request)
    store = get_session_store()
    visitor_id, _ = resolve_visitor_id(request, settings)

    # Keyed by IP, not visitor: locked visitors may have no cookie yet,
    # and a fresh-minted id every request would never accumulate.
    if not await store.check_rate_limit(
        f"pdf:{get_client_ip(request, settings)}", max_requests=5, window=600.0
    ):
        raise HTTPException(
            status_code=429,
            detail="Too many download attempts. Please wait a few minutes.",
        )

    await store.update_metadata(visitor_id)
    unlocked = await store.get_remaining_quota(visitor_id, settings.free_chat_limit) is None
    if not unlocked:
        raise HTTPException(status_code=403, detail=PDF_LOCKED_MESSAGE)

    try:
        pdf_bytes = await asyncio.to_thread(render_resume_pdf)
    except Exception as exc:
        logger.exception("Failed to render resume PDF")
        raise HTTPException(status_code=500, detail="Unable to render the PDF right now.") from exc
    logger.info(
        "Resume PDF downloaded by visitor %s",
        anonymize_session_id(visitor_id, settings.session_hash_secret),
    )
    final = Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="Dakota-Radigan-Resume.pdf"',
            "Cache-Control": "no-store",
        },
    )
    set_visitor_cookie(final, visitor_id, settings)
    return final

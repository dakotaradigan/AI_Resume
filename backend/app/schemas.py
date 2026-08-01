"""Request/response models for the public API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = Field(default=None, max_length=100)


class UnlockRequest(BaseModel):
    password: str
    # Accepted for backward compatibility but ignored: unlock is keyed to the
    # server-minted visitor cookie, not the client-supplied session id.
    session_id: str | None = Field(default=None, max_length=100)


class JDMatchRequest(BaseModel):
    jd_text: str = Field(..., min_length=1)
    mode: Literal["analysis", "brief"] = "analysis"
    session_id: str | None = Field(default=None, max_length=100)


class UnlockResponse(BaseModel):
    success: bool
    message: str


class FeedbackRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=100)
    rating: Literal["up", "down"]
    comment: str = Field(default="", max_length=500)
    trigger: Literal["first_response", "password_unlock", ""] = ""


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    sources: list[str] = Field(default_factory=list)
    used_rag: bool = False

"""Anthropic client construction, model routing, and model-id checks."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from anthropic import AsyncAnthropic

from app.config import Settings

logger = logging.getLogger(__name__)

_ROUTER_SYSTEM = (
    "Classify the user question about a resume as 'simple' (single factual "
    "lookup) or 'complex' (synthesis, comparison, multi-part, or open-ended). "
    "Reply with exactly one word: simple or complex."
)

# Newer Anthropic models (Sonnet 5, Opus 4.7/4.8, Fable/Mythos) reject requests
# that set non-default sampling params like temperature with 400 Bad Request.
_NO_SAMPLING_MODEL_MARKERS = ("sonnet-5", "opus-4-7", "opus-4-8", "fable", "mythos")

# Anthropic model ids are lowercase words joined by hyphens (claude-opus-4-8).
# Anything else — capitals, dots, spaces — 404s on every request, which
# presents as "chat is down" while deploys look green.
_MODEL_ID_RE = re.compile(r"^claude-[a-z0-9-]+$")


def make_anthropic_client(settings: Settings) -> AsyncAnthropic:
    return AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.api_timeout_seconds,
        max_retries=3,  # Built-in retry with exponential backoff
    )


def model_short_label(model_id: str) -> str:
    """Human label for status events: 'claude-sonnet-5' -> 'Sonnet'."""
    lowered = model_id.lower()
    for family in ("opus", "sonnet", "haiku"):
        if family in lowered:
            return family.capitalize()
    return model_id


def sampling_kwargs(model_id: str, temperature: float) -> dict[str, Any]:
    """Sampling params for a messages call, omitted for models that reject them."""
    lowered = model_id.lower()
    if any(marker in lowered for marker in _NO_SAMPLING_MODEL_MARKERS):
        return {}
    return {"temperature": temperature}


def is_fast_path_simple(message: str) -> bool:
    """Trivial queries skip the classifier and go straight to the simple model."""
    if len(message) >= 120:
        return False
    lowered = message.lower()
    return " and " not in lowered and "," not in message and message.count("?") <= 1


async def route_model(
    message: str, client: AsyncAnthropic, settings: Settings
) -> tuple[str, str]:
    """Pick the generation model for this turn. Returns (model_id, reason).

    Fails safe: any classifier error routes to the primary (most capable)
    model, bounded by the existing rate and daily limits.
    """
    if is_fast_path_simple(message):
        return settings.anthropic_model_simple, "fast-path"
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=settings.anthropic_router_model,
                max_tokens=4,
                **sampling_kwargs(settings.anthropic_router_model, 0.0),
                system=_ROUTER_SYSTEM,
                messages=[{"role": "user", "content": [{"type": "text", "text": message}]}],
            ),
            timeout=2.0,
        )
        label = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip().lower()
    except Exception:
        logger.warning("Model router classification failed; using primary model")
        return settings.anthropic_model, "router-error"
    if label == "simple":
        return settings.anthropic_model_simple, "simple"
    return settings.anthropic_model, "complex"


def build_api_messages(history: list[dict], message: str) -> list[dict]:
    # Drop any history entries with roles the Messages API rejects
    # (e.g. "system" summaries written by older compaction code).
    return [
        *(msg for msg in history if msg.get("role") in ("user", "assistant")),
        {"role": "user", "content": [{"type": "text", "text": message}]},
    ]


def warn_on_suspicious_model_ids(settings: Settings) -> None:
    for env_name, value in (
        ("ANTHROPIC_MODEL", settings.anthropic_model),
        ("ANTHROPIC_MODEL_SIMPLE", settings.anthropic_model_simple),
        ("ANTHROPIC_ROUTER_MODEL", settings.anthropic_router_model),
    ):
        looks_like_claude_id = value.lower().startswith("claude")
        if looks_like_claude_id and not _MODEL_ID_RE.match(value):
            logger.error(
                "%s looks invalid: %r — model ids are lowercase with hyphens "
                "(e.g. claude-opus-4-8); the API will reject every request.",
                env_name,
                value,
            )

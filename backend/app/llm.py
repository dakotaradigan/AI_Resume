"""Anthropic client construction, model routing, and model-id checks."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx
from anthropic import AsyncAnthropic

from app.config import Settings

logger = logging.getLogger(__name__)

_ROUTER_SYSTEM = (
    "Classify the user question about a resume as 'simple' (single factual "
    "lookup) or 'complex' (synthesis, comparison, multi-part, or open-ended). "
    "Reply with exactly one word: simple or complex."
)

# TypeSafe Jev router: one typed `Choice` question. Labels double as the
# routing reason reported in status events, so they match the Claude
# classifier's vocabulary. Jev returns a probability per label plus a
# confidence for the distribution — no text to parse.
#
# Per the TypeSafe skill: the question id is not sent to the model, so the
# instructions carry the full judgment and reference the named state field;
# criteria are structured (description + examples) because examples sharpen
# the boundary between the two tiers better than prose alone.
_ROUTE_QUESTION_ID = "model_route"
_ROUTE_STATE_FIELD = "visitor_question"
_ROUTE_INSTRUCTIONS = (
    f"`{_ROUTE_STATE_FIELD}` is a recruiter or hiring manager asking about "
    "Dakota's resume. A capable general model answers most questions well. "
    "Choose `complex` only when a good answer must weigh several roles or "
    "projects against each other or against a job; otherwise choose `simple`."
)
_ROUTE_CHOICES = {
    "simple": {
        "description": (
            "The default. Any question about one topic: a skill, a role, an "
            "employer, a project, a date, a summary of one area of experience, "
            "or a yes/no question. Open-ended is fine as long as it is one topic."
        ),
        "examples": [
            "Does Dakota know Python?",
            "Tell me about Dakota's AI experience.",
            "What did he do at Parametric?",
            "What projects has he built?",
            "Is he PCAP certified?",
        ],
    },
    "complex": {
        "description": (
            "Only when the answer must compare or combine several roles or "
            "projects: side-by-side comparisons, fit assessments against a "
            "specific job, strengths-and-gaps analysis, or a multi-part "
            "question spanning different areas of the resume."
        ),
        "examples": [
            "Compare his product management and AI engineering experience.",
            "Would he be a good fit for a senior AI PM role, and why?",
            "What are his biggest strengths and gaps for a fintech role?",
            "Walk me through his career arc and how each role built on the last.",
        ],
    },
}
# Sonnet is the default tier. Opus only when Jev is clearly convinced the
# question is complex: its probability for `complex` must reach this. Using
# the label alone (or Jev's confidence) sent uncertain questions to Opus,
# which is the expensive direction to be wrong in.
_ROUTE_COMPLEX_MIN_PROBABILITY = 0.7
# No retries on purpose: routing runs alongside retrieval and must not add
# serial latency. A failed call simply routes to the primary model.
_ROUTE_TIMEOUT_SECONDS = 2.0

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


def router_short_label(route_reason: str, settings: Settings) -> str:
    """Which router produced this turn's decision, for status events.

    'Jev' when TypeSafe classified, the Claude router model's family when the
    text classifier did, 'Rules' for the no-model fast path, and 'Fallback'
    when the router failed and the primary model was used by default.
    """
    if route_reason == "fast-path":
        return "Rules"
    if route_reason == "router-error":
        return "Fallback"
    if settings.typesafe_api_key:
        return "Jev"
    return model_short_label(settings.anthropic_router_model)


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


def typesafe_route_payload(message: str, settings: Settings) -> dict[str, Any]:
    """Request body for TypeSafe's /v1/systemone endpoint."""
    return {
        "state": {_ROUTE_STATE_FIELD: message},
        "model": settings.typesafe_model,
        "questions": {
            _ROUTE_QUESTION_ID: {
                "type": "choice",
                "instructions": _ROUTE_INSTRUCTIONS,
                "criteria": _ROUTE_CHOICES,
            }
        },
    }


async def classify_with_typesafe(
    message: str, settings: Settings, http: httpx.AsyncClient
) -> float:
    """Ask Jev which tier fits. Returns the probability the question is complex.

    Raises on transport errors, non-2xx responses, or a response that does not
    carry a probability for every label — callers treat all of those as
    "router unavailable".
    """
    response = await http.post(
        f"{settings.typesafe_base_url.rstrip('/')}/v1/systemone",
        json=typesafe_route_payload(message, settings),
        headers={"Authorization": f"Bearer {settings.typesafe_api_key}"},
        timeout=_ROUTE_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    answer = response.json()["answers"][_ROUTE_QUESTION_ID]
    probabilities = answer["probabilities"]
    missing = set(_ROUTE_CHOICES) - set(probabilities)
    if missing:
        raise ValueError(f"TypeSafe response lacks probabilities for {sorted(missing)}")
    return float(probabilities["complex"])


async def check_typesafe_credentials(
    settings: Settings, http: httpx.AsyncClient
) -> None:
    """Raise if the TypeSafe key cannot list models (no tokens spent)."""
    response = await http.get(
        f"{settings.typesafe_base_url.rstrip('/')}/v1/models",
        headers={"Authorization": f"Bearer {settings.typesafe_api_key}"},
        timeout=5.0,
    )
    response.raise_for_status()


_typesafe_http: httpx.AsyncClient | None = None


def typesafe_http_client() -> httpx.AsyncClient:
    """Process-wide pooled client for router calls (created on first use)."""
    global _typesafe_http
    if _typesafe_http is None:
        _typesafe_http = httpx.AsyncClient()
    return _typesafe_http


async def route_model(
    message: str,
    client: AsyncAnthropic,
    settings: Settings,
    http: httpx.AsyncClient | None = None,
) -> tuple[str, str]:
    """Pick the generation model for this turn. Returns (model_id, reason).

    Uses TypeSafe Jev when TYPESAFE_API_KEY is set, else the Claude classifier.
    Jev is cheap and sub-second, so it judges every message; the rule-based
    fast path only exists to spare the Claude classifier a model call.
    Fails safe: any classifier error routes to the primary (most capable)
    model, bounded by the existing rate and daily limits.
    """
    if settings.typesafe_api_key:
        try:
            p_complex = await classify_with_typesafe(
                message, settings, http or typesafe_http_client()
            )
        except Exception:
            logger.warning("TypeSafe router classification failed; using primary model")
            return settings.anthropic_model, "router-error"
        logger.info("Jev route p_complex=%.2f", p_complex)
        if p_complex >= _ROUTE_COMPLEX_MIN_PROBABILITY:
            return settings.anthropic_model, "complex"
        return settings.anthropic_model_simple, "simple"
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

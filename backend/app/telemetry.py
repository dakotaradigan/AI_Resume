"""OpenTelemetry tracing: spans for requests, outgoing HTTP calls, and MCP tool calls.

Off unless OTEL_TRACES_EXPORTER is set:
- "console" prints each finished span to stdout (local learning, no account).
- "otlp" sends spans over OTLP/HTTP to the endpoint and headers in the standard
  OTEL_EXPORTER_OTLP_TRACES_ENDPOINT / OTEL_EXPORTER_OTLP_TRACES_HEADERS
  variables (Datadog, an OpenTelemetry Collector, or any OTLP backend).

Automatic spans: FastAPI (one server span per request) and httpx (one client
span per outgoing call). The Anthropic, OpenAI, Qdrant and TypeSafe clients all
send over httpx, so every model and vector-store call shows up with no code at
the call site. Manual spans: one execute_tool span per MCP tool call
(tool_span), named and attributed per the OpenTelemetry GenAI semantic
conventions.

Tool arguments and results are visitor content (a question, a pasted job
description). They are recorded only when
OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true, and always through
content_attribute.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.trace import Span, StatusCode

from app.config import Settings
from app.logging_setup import redact

logger = logging.getLogger(__name__)

SERVICE_NAME = "resume-assistant"
EXPORTERS = {"console", "otlp"}

# Longest string a content attribute may hold. Datadog and most backends cap
# span size, and get_resume returns the whole résumé on every call.
MAX_CONTENT_CHARS = 4_096

# A proxy until configure_tracing installs a real provider: every span is a
# no-op (is_recording() is False) when tracing is off.
_tracer = trace.get_tracer(__name__)
_provider_installed = False
_capture_content = False


def configure_tracing(app: FastAPI, settings: Settings) -> bool:
    """Install the tracer provider and automatic instrumentation.

    Returns True when tracing is on. The provider and the httpx patch are
    process-global, so they are installed once; each app built (the test suite
    builds many) gets its own FastAPI instrumentation.
    """
    global _provider_installed, _capture_content

    exporter_name = settings.otel_traces_exporter
    if not exporter_name or exporter_name == "none":
        return False
    if exporter_name not in EXPORTERS:
        logger.warning(
            "OTEL_TRACES_EXPORTER=%r is not one of %s; tracing stays off.",
            exporter_name, sorted(EXPORTERS),
        )
        return False

    # Imported here so a box with tracing off never loads the SDK.
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    if not _provider_installed:
        if exporter_name == "console":
            exporter = ConsoleSpanExporter()
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            # Reads the endpoint and headers from the OTEL_EXPORTER_OTLP_* env vars.
            exporter = OTLPSpanExporter()

        # Resource.create also reads OTEL_RESOURCE_ATTRIBUTES, which is how a
        # backend-specific flag (Datadog's dd_llmobs_enabled) is passed in.
        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": SERVICE_NAME,
                    "deployment.environment.name": settings.environment,
                }
            )
        )
        # Batching: spans queue in memory and a background thread sends them
        # every few seconds, so a request never waits on the backend.
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        HTTPXClientInstrumentor().instrument()
        _provider_installed = True

    FastAPIInstrumentor.instrument_app(
        app,
        # Railway and the uptime probe poll /health; those spans are noise.
        excluded_urls="/health",
        # Without this, every SSE chunk of a streamed reply is its own span.
        exclude_spans=["receive", "send"],
    )
    _capture_content = settings.otel_capture_content
    logger.info(
        "Tracing on: exporter=%s, tool content capture=%s",
        exporter_name, _capture_content,
    )
    return True


def content_attribute(value: Any) -> str:
    """Turn a tool's arguments or result into a span attribute string.

    Called only when content capture is on. The string leaves the app for
    the tracing backend, so it must be safe to store there.

    TODO(Dakota): implement in 5-10 lines.
    """
    raise NotImplementedError


@contextmanager
def tool_span(name: str, arguments: dict[str, Any]) -> Iterator[Span]:
    """An execute_tool span around one MCP tool call.

    record_exception=False: the default would attach the exception's message
    and traceback, including chained causes (an upstream error's text), to the
    span. record_tool_error records only the visitor-safe message instead.
    """
    with _tracer.start_as_current_span(
        f"execute_tool {name}",
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", name)
        span.set_attribute("gen_ai.tool.type", "function")
        _set_content(span, "gen_ai.tool.call.arguments", arguments)
        yield span


def record_tool_result(span: Span, result: Any) -> None:
    _set_content(span, "gen_ai.tool.call.result", result)


def _set_content(span: Span, key: str, value: Any) -> None:
    # is_recording() is False when tracing is off: skip the serializing.
    if not (_capture_content and span.is_recording()):
        return
    try:
        span.set_attribute(key, content_attribute(value))
    except Exception:
        # Tracing is a side channel: a bug here costs an attribute, never
        # the caller's answer.
        logger.warning("Could not record %s on the tool span", key, exc_info=True)


def record_tool_error(span: Span, error_type: str, safe_message: str) -> None:
    """Mark the span failed with the message the caller saw.

    Recorded whether or not content capture is on: refusals (rate limit, quota)
    are the security signal, and the message is visitor-safe by construction.
    """
    span.set_attribute("error.type", error_type)
    span.set_status(StatusCode.ERROR, safe_message)

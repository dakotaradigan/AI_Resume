"""OpenTelemetry tracing for the resume agent.

Off unless OTEL_TRACES_EXPORTER is set:
- "console" prints each finished span to stdout (local learning, no account).
- "otlp" sends spans over OTLP/HTTP to the endpoint and headers in the standard
  OTEL_EXPORTER_OTLP_TRACES_ENDPOINT / OTEL_EXPORTER_OTLP_TRACES_HEADERS
  variables (Datadog, an OpenTelemetry Collector, or any OTLP backend).

Automatic spans: FastAPI's built-in telemetry (one server span per request,
FASTAPI_TELEMETRY) and the httpx instrumentation (one client span per outgoing
call: Anthropic, OpenAI, Qdrant and TypeSafe all send over httpx).

Manual spans, named per the OpenTelemetry GenAI semantic conventions, so an
LLM backend (Datadog LLM Observability) can draw one tree per turn:

    invoke_agent resume-assistant   one chat turn or fit analysis (web routes)
    execute_tool <name>             one MCP tool call (the root for MCP callers)
      retrieval resume              the RAG search: query, documents, scores
      route_model                   which model, and why (Jev probability)
      chat <model>                  one Claude call: tokens, cost, finish reason

Visitor content (questions, replies, tool arguments and results) is recorded
only when OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true, always
redacted and capped (safe_text). Everything else (models, tokens, timings,
résumé source titles, refusals) is recorded whenever tracing is on.

Tracing is a side channel: a failure in it may cost an attribute, never the
caller's answer.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
from contextlib import contextmanager
from typing import Any, AsyncIterator, Callable, Iterator, MutableMapping

from analytics.analytics import anonymize_session_id
from fastapi import HTTPException
from opentelemetry import context, trace
from opentelemetry.trace import Span, SpanKind, StatusCode

from app.config import Settings
from app.llm import estimate_cost_usd, usage_record
from app.logging_setup import redact

logger = logging.getLogger(__name__)

SERVICE_NAME = "resume-assistant"
AGENT_NAME = "resume-assistant"
EXPORTERS = {"console", "otlp"}

# Longest content string a span may hold. Backends cap span size, and
# get_resume returns the whole résumé on every call.
MAX_CONTENT_CHARS = 4_096
TRUNCATION_MARKER = "…[truncated]"

# A proxy until configure_tracing installs a real provider: every span is a
# no-op (is_recording() is False) when tracing is off.
_tracer = trace.get_tracer(__name__)
_provider_installed = False
_capture_content = False


# --- Setup ------------------------------------------------------------------


def _skip_health(scope: MutableMapping[str, Any]) -> bool:
    # Railway and the uptime probe poll /health; those spans are noise.
    return scope.get("path", "").startswith("/health")


# FastAPI's built-in OpenTelemetry support (FastAPI(telemetry=...)). It traces
# each request with whatever provider configure_tracing installs, and stays
# idle while none is installed.
FASTAPI_TELEMETRY: dict[str, Any] = {
    "tracing": True,
    # Off: its log export carries exception messages and stack traces, which
    # can hold credentials. The app's own JSON logs are redacted.
    "logs": False,
    # Off: no metrics pipeline is set up, and Datadog bills OTel metrics as
    # custom metrics. Request timing is already on the server span.
    "metrics": False,
    # Off: dependency and endpoint sub-spans are noise here, and for a
    # streamed reply the endpoint span ends before the stream does.
    "operation_spans": False,
    # Never let FastAPI build its own exporters from env vars; one setup path.
    "auto_configure": False,
    "exclude": _skip_health,
}


def configure_tracing(settings: Settings) -> bool:
    """Install the tracer provider and instrument outgoing httpx calls.

    Returns True when tracing is on. Both are process-global, so they are
    installed once even though the test suite builds many apps. Incoming
    requests are traced by FastAPI itself (FASTAPI_TELEMETRY).
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

    _capture_content = settings.otel_capture_content
    logger.info(
        "Tracing on: exporter=%s, content capture=%s", exporter_name, _capture_content
    )
    return True


# --- Content: what visitor text may leave the app -----------------------------


def safe_text(text: str) -> str:
    """Redact credential shapes, then cap the length.

    The order matters: cutting first can leave a key stub too short for the
    redaction patterns to recognize, and the stub would reach the backend.
    """
    text = redact(text)
    if len(text) > MAX_CONTENT_CHARS:
        text = text[: MAX_CONTENT_CHARS - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
    return text


def _hide_session_id(value: Any) -> Any:
    """A session id is a live identifier: record whether one was sent or
    returned, never its value (gen_ai.conversation.id carries the hashed
    form)."""
    if isinstance(value, dict) and value.get("session_id"):
        return {**value, "session_id": "<hidden>"}
    return value


def content_attribute(value: Any) -> str:
    """Tool arguments or results as redacted, capped JSON text.

    ensure_ascii=False keeps "résumé" readable; default=str turns values JSON
    cannot encode (dates) into text instead of failing.
    """
    return safe_text(json.dumps(value, ensure_ascii=False, default=str))


def _messages_attribute(role: str, text: str, finish_reason: str | None = None) -> str:
    """One message in the GenAI convention's shape. The text is made safe
    before serializing, so a long reply is cut without breaking the JSON."""
    message: dict[str, Any] = {
        "role": role,
        "parts": [{"type": "text", "content": safe_text(text)}],
    }
    if finish_reason:
        message["finish_reason"] = finish_reason
    return json.dumps([message], ensure_ascii=False)


def _set_content(span: Span, key: str, make: Callable[[], str]) -> None:
    """Record visitor content, only when capture is on. ``make`` builds the
    string lazily: with tracing or capture off, nothing is serialized."""
    if not (_capture_content and span.is_recording()):
        return
    try:
        span.set_attribute(key, make())
    except Exception:
        logger.warning("Could not record %s on a span", key, exc_info=True)


def _side_channel(fn: Callable[..., None]) -> Callable[..., None]:
    """Log and swallow any failure in a record_* helper."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.warning("Tracing failed in %s", fn.__name__, exc_info=True)

    return wrapper


def _mark_failed(span: Span, exc: BaseException) -> None:
    """Failed status with a low-detail error.type, never the exception text
    (an upstream error message can carry a credential)."""
    if isinstance(exc, HTTPException):
        error_type = str(exc.status_code)
    elif isinstance(exc, (asyncio.CancelledError, GeneratorExit)):
        error_type = "cancelled"  # the visitor hung up mid-stream
    else:
        error_type = type(exc).__name__
    span.set_attribute("error.type", error_type)
    span.set_status(StatusCode.ERROR)


# --- invoke_agent: one turn of the resume agent -----------------------------


def start_agent_span(kind: str, question: str) -> Span:
    """Start (not enter) the root span of one turn. ``kind`` is "chat" or
    "fit_analysis". Use agent_span for a plain request, or traced_stream for
    a streamed one."""
    span = _tracer.start_span(f"invoke_agent {AGENT_NAME}")
    span.set_attribute("gen_ai.operation.name", "invoke_agent")
    span.set_attribute("gen_ai.agent.name", AGENT_NAME)
    span.set_attribute("app.turn.kind", kind)
    _set_content(span, "gen_ai.input.messages", lambda: _messages_attribute("user", question))
    return span


@contextmanager
def agent_span(kind: str, question: str) -> Iterator[Span]:
    """The turn's root span, current for the block (non-streaming routes)."""
    span = start_agent_span(kind, question)
    with trace.use_span(
        span, end_on_exit=True, record_exception=False, set_status_on_exception=False
    ):
        try:
            yield span
        except BaseException as exc:
            _mark_failed(span, exc)
            raise


async def traced_stream(span: Span, body: AsyncIterator[str]) -> AsyncIterator[str]:
    """Run a streamed response body with ``span`` as its current span.

    The span is current only while the body runs up to its next chunk, and is
    detached before the chunk goes out: a context held across a yield leaks
    into whatever code runs between chunks. Ends the span when the body
    finishes, fails, or the visitor hangs up.
    """
    try:
        while True:
            token = context.attach(trace.set_span_in_context(span))
            try:
                chunk = await anext(body)
            except StopAsyncIteration:
                break
            finally:
                context.detach(token)
            yield chunk
    except BaseException as exc:
        _mark_failed(span, exc)
        raise
    finally:
        await body.aclose()
        span.end()


@_side_channel
def record_agent_output(span: Span, reply: str) -> None:
    _set_content(span, "gen_ai.output.messages", lambda: _messages_attribute("assistant", reply))


@_side_channel
def record_conversation(span: Span, session_id: str, settings: Settings) -> None:
    """Group a visitor's turns. The id is hashed the way the analytics files
    hash it: the live session id never leaves the app."""
    span.set_attribute(
        "gen_ai.conversation.id",
        anonymize_session_id(session_id, settings.session_hash_secret),
    )


# --- execute_tool: one MCP tool call ------------------------------------------


@contextmanager
def tool_span(name: str, arguments: dict[str, Any]) -> Iterator[Span]:
    """An execute_tool span around one MCP tool call.

    record_exception=False: the default would attach the exception's message
    and traceback, including chained causes, to the span. record_tool_error
    records only the visitor-safe message instead.
    """
    with _tracer.start_as_current_span(
        f"execute_tool {name}",
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", name)
        span.set_attribute("gen_ai.tool.type", "function")
        _set_content(
            span,
            "gen_ai.tool.call.arguments",
            lambda: content_attribute(_hide_session_id(arguments)),
        )
        yield span


@_side_channel
def record_tool_result(span: Span, result: Any) -> None:
    _set_content(
        span, "gen_ai.tool.call.result", lambda: content_attribute(_hide_session_id(result))
    )


def record_tool_error(span: Span, error_type: str, safe_message: str) -> None:
    """Mark the span failed with the message the caller saw.

    Recorded whether or not content capture is on: refusals (rate limit, quota)
    are the security signal, and the message is visitor-safe by construction.
    """
    span.set_attribute("error.type", error_type)
    span.set_status(StatusCode.ERROR, safe_message)


# --- retrieval and routing ----------------------------------------------------


@contextmanager
def retrieval_span(query: str) -> Iterator[Span]:
    with _tracer.start_as_current_span(
        "retrieval resume", record_exception=False, set_status_on_exception=False
    ) as span:
        span.set_attribute("gen_ai.operation.name", "retrieval")
        span.set_attribute("gen_ai.data_source.id", "resume")
        _set_content(span, "gen_ai.retrieval.query.text", lambda: safe_text(query))
        yield span


@_side_channel
def record_retrieval(span: Span, used_rag: bool, sources: list[dict[str, Any]]) -> None:
    # Résumé chunk titles and scores: public data, not visitor content, so
    # recorded whenever tracing is on.
    span.set_attribute("app.retrieval.used_rag", used_rag)
    span.set_attribute(
        "gen_ai.retrieval.documents",
        json.dumps(
            [{"id": s["title"], "score": s["score"]} for s in sources], ensure_ascii=False
        ),
    )


@contextmanager
def route_span() -> Iterator[Span]:
    """The router's decision. Not a model call, but it carries a gen_ai
    operation name so an LLM backend keeps it in the turn's tree."""
    with _tracer.start_as_current_span(
        "route_model", record_exception=False, set_status_on_exception=False
    ) as span:
        span.set_attribute("gen_ai.operation.name", "route_model")
        yield span


@_side_channel
def record_route(span: Span, model_id: str, reason: str) -> None:
    span.set_attribute("app.route.model", model_id)
    span.set_attribute("app.route.reason", reason)


# --- chat: one Claude call ----------------------------------------------------


@contextmanager
def chat_span(model: str, max_tokens: int, user_text: str) -> Iterator[Span]:
    """A chat span around one Anthropic messages call. Pass the response to
    record_chat_response.

    Started without becoming the current span: the streaming routes send
    chunks to the visitor inside it, and a current span must not be held
    across a yield. It is still a child of the span current when it starts.
    Only the turn's newest user message is recorded, not the history (earlier
    turns are in their own spans, grouped by gen_ai.conversation.id).
    """
    span = _tracer.start_span(f"chat {model}", kind=SpanKind.CLIENT)
    span.set_attribute("gen_ai.operation.name", "chat")
    span.set_attribute("gen_ai.provider.name", "anthropic")
    span.set_attribute("gen_ai.request.model", model)
    span.set_attribute("gen_ai.request.max_tokens", max_tokens)
    _set_content(span, "gen_ai.input.messages", lambda: _messages_attribute("user", user_text))
    try:
        yield span
    except BaseException as exc:
        _mark_failed(span, exc)
        raise
    finally:
        span.end()


@_side_channel
def record_chat_response(span: Span, message: Any) -> None:
    """Model, finish reason, tokens, estimated cost, and (with capture on)
    the reply text, from one messages response."""
    model = getattr(message, "model", None)
    if isinstance(model, str):
        span.set_attribute("gen_ai.response.model", model)
    response_id = getattr(message, "id", None)
    if isinstance(response_id, str):
        span.set_attribute("gen_ai.response.id", response_id)
    stop_reason = getattr(message, "stop_reason", None)
    if not isinstance(stop_reason, str):
        stop_reason = None
    if stop_reason:
        span.set_attribute("gen_ai.response.finish_reasons", [stop_reason])

    usage = usage_record(message)
    if usage:
        cache_read = usage["cache_read_input_tokens"]
        cache_write = usage["cache_creation_input_tokens"]
        # Anthropic's input_tokens excludes cached tokens; the GenAI convention
        # counts all input, with the cached parts also broken out.
        span.set_attribute(
            "gen_ai.usage.input_tokens", usage["input_tokens"] + cache_read + cache_write
        )
        span.set_attribute("gen_ai.usage.output_tokens", usage["output_tokens"])
        span.set_attribute("gen_ai.usage.cache_read.input_tokens", cache_read)
        span.set_attribute("gen_ai.usage.cache_creation.input_tokens", cache_write)
        # The same list-price estimate the analytics files store, to compare
        # with the backend's own estimate.
        cost = estimate_cost_usd(model, usage) if isinstance(model, str) else None
        if cost is not None:
            span.set_attribute("app.cost_usd_estimate", cost)

    reply = "".join(
        getattr(block, "text", "")
        for block in getattr(message, "content", None) or []
        if getattr(block, "type", None) == "text"
    )
    _set_content(
        span,
        "gen_ai.output.messages",
        lambda: _messages_attribute("assistant", reply, stop_reason),
    )

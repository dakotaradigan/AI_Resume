"""JSON logging for deployed environments, with credential redaction.

Every record, the app's own lines, uvicorn's, a library's traceback, passes
through ``redact`` before it is written. The log sites themselves are
written not to carry secrets; this layer is the net under them, for the
values that arrive inside exception text: a provider URL with a key in it,
a bearer header echoed by an HTTP client, a store DSN with its password.
It is pattern-based, so it catches credential shapes, not arbitrary
personal data, which is why the sites still matter.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.request_context import RequestContextFilter

# Credential shapes, replaced wholesale. The CI secret scan (gitleaks) runs its
# own built-in rules, not this tuple; the tests build their fixtures at runtime
# so that no committed line is secret-shaped for it.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # user:password@ inside any URL / DSN (redis://, postgres://, https://).
    (re.compile(r"(://)[^/\s@:]+:[^/\s@]+@"), r"\1***:***@"),
    # Query-string or key=value credentials.
    (
        re.compile(
            r"(?i)\b(token|access_token|refresh_token|api_key|apikey|secret|"
            r"password|passwd|pwd|authorization|client_secret)=([^&\s\"']+)"
        ),
        r"\1=***",
    ),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer ***"),
    # Provider / cloud key formats. No leading \b: visitor text can glue a
    # pasted key to the word before it ("mykeysk-ant-..."), and \b needs a
    # non-word character there. These prefixes are distinctive on their own.
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"), "sk-ant-***"),
    (re.compile(r"sk-proj-[A-Za-z0-9_-]{8,}"), "sk-proj-***"),
    (re.compile(r"AKIA[0-9A-Z]{16}\b"), "AKIA***"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}\b"), "ghp_***"),
    # Generic "sk-" key. Plain "sk-" is also the end of task-, risk-, disk-,
    # so it gets two rules. Standalone, any 20+ character body counts:
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "sk-***"),
    # Glued to a word, the body must also mix upper case, lower case and
    # digits. A random key does; a hex id or a word ("task-9f86d0...") does
    # not. A glued key with no digit slips through (about 0.03% of 48-char
    # keys); over-redacting every "task-<hex>" id was the worse trade.
    (
        re.compile(
            r"sk-(?=[A-Za-z0-9]*[A-Z])(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[0-9])"
            r"[A-Za-z0-9]{20,}"
        ),
        "sk-***",
    ),
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
        "-----BEGIN PRIVATE KEY----- *** -----END PRIVATE KEY-----",
    ),
)


def redact(text: str) -> str:
    """Scrub credential shapes from free text. Idempotent; a clean string
    comes back unchanged (the common case, so this stays cheap)."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class JsonLogFormatter(logging.Formatter):
    """Single-line JSON records so deployed logs are machine-greppable.
    Message and traceback text are redacted (module docstring)."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        # Present only while a request is in flight (request_context.py), so
        # startup and shutdown lines stay uncluttered.
        request_id = getattr(record, "request_id", "")
        if request_id:
            entry["request_id"] = request_id
        if record.exc_info:
            entry["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry)


def configure_logging() -> None:
    """Attach a JSON handler when nothing else configured the root logger.

    Under uvicorn the root logger has no handlers, so app logs would fall back
    to lastResort plain text; tests and embedders that configure logging first
    are left untouched.
    """
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    handler.addFilter(RequestContextFilter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)

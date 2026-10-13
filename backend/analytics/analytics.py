"""
Analytics logging for user queries.

PRIVACY NOTE: This file creates queries.jsonl which contains user questions.
The queries.jsonl file is gitignored to protect user privacy.
"""

import fcntl
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def anonymize_session_id(session_id: str, secret: str) -> str:
    """HMAC-SHA256 of a session id, truncated to 16 hex chars.

    Keeps analytics rows correlatable per session without ever storing the
    live bearer id (see docs/security-assessment SEC-01). Callers pass the
    configured SESSION_HASH_SECRET.
    """
    digest = hmac.new(secret.encode(), session_id.encode(), hashlib.sha256)
    return digest.hexdigest()[:16]

ANALYTICS_DIR = Path(os.getenv("ANALYTICS_DIR", str(Path(__file__).parent)))
ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
ANALYTICS_FILE = ANALYTICS_DIR / "queries.jsonl"
FEEDBACK_FILE = ANALYTICS_DIR / "feedback.jsonl"


def log_query(
    session_id: str,
    query: str,
    response: str = "",
    model: str = "",
    route_reason: str = "",
    usage: dict[str, int] | None = None,
    cost_usd: float | None = None,
) -> None:
    """
    Log a user query for analytics.

    Args:
        session_id: Session identifier (anonymized)
        query: User's question
        response: Full bot response (used by evals judges)
        model: Model that generated the response (router evals)
        route_reason: Why the router picked that model (router evals)
        usage: Token counts for the generation call (input, output, cache
            read, cache write), when the response carried them
        cost_usd: List-price estimate for that call (cost per route evals)
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "query": query,
        "response": response,
    }
    if model:
        entry["model"] = model
    if route_reason:
        entry["route_reason"] = route_reason
    if usage:
        entry["usage"] = usage
    if cost_usd is not None:
        entry["cost_usd"] = cost_usd

    try:
        with open(ANALYTICS_FILE, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(json.dumps(entry) + "\n")
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        logger.warning(f"Failed to log query: {e}")


def _entry_timestamp(line: str) -> datetime | None:
    """The entry's timestamp, or None when the line cannot be dated."""
    try:
        stamp = datetime.fromisoformat(json.loads(line)["timestamp"])
    except (ValueError, KeyError, TypeError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def prune_old_entries(path: Path, retention_days: int, *, now: datetime | None = None) -> int:
    """Drop entries older than ``retention_days`` from a JSONL file, in place.

    Returns the number dropped. 0 days keeps everything. A line that cannot
    be dated is kept: a malformed line is no reason to lose data. The
    rewrite happens under the same lock the writers take, so an append
    landing during the prune is never lost.
    """
    if retention_days <= 0 or not path.exists():
        return 0
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
    dropped = 0
    with open(path, "r+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            kept: list[str] = []
            for line in f:
                if not line.strip():
                    continue
                stamp = _entry_timestamp(line)
                if stamp is not None and stamp < cutoff:
                    dropped += 1
                else:
                    kept.append(line if line.endswith("\n") else line + "\n")
            if dropped:
                f.seek(0)
                f.truncate()
                f.write("".join(kept))
                f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return dropped


def prune_analytics(retention_days: int) -> dict[str, int]:
    """Apply the retention window to both files; counts dropped per file."""
    return {
        "queries": prune_old_entries(ANALYTICS_FILE, retention_days),
        "feedback": prune_old_entries(FEEDBACK_FILE, retention_days),
    }


def log_feedback(session_id: str, rating: str, comment: str = "", trigger: str = "") -> None:
    """
    Log user feedback (thumbs up/down).

    Args:
        session_id: Session identifier
        rating: "up" or "down"
        comment: Optional comment (typically on thumbs down)
        trigger: What triggered the feedback prompt ("first_response" or "password_unlock")
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "rating": rating,
        "comment": comment,
        "trigger": trigger
    }

    try:
        with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(json.dumps(entry) + "\n")
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        logger.warning(f"Failed to log feedback: {e}")

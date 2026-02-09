"""
Analytics logging for user queries.

PRIVACY NOTE: This file creates queries.jsonl which contains user questions.
The queries.jsonl file is gitignored to protect user privacy.
"""

import fcntl
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ANALYTICS_FILE = Path(__file__).parent / "queries.jsonl"
FEEDBACK_FILE = Path(__file__).parent / "feedback.jsonl"


def log_query(session_id: str, query: str, response: str = "") -> None:
    """
    Log a user query for analytics.

    Args:
        session_id: Session identifier (anonymized)
        query: User's question
        response: Full bot response (used by evals judges)
    """
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "session_id": session_id,
        "query": query,
        "response": response,
    }

    try:
        with open(ANALYTICS_FILE, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(json.dumps(entry) + "\n")
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        logger.warning(f"Failed to log query: {e}")


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
        "timestamp": datetime.utcnow().isoformat(),
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

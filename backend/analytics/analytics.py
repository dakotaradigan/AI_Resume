"""
Analytics logging for user queries.

PRIVACY NOTE: This file creates queries.json which contains user questions.
The queries.json file is gitignored to protect user privacy.
"""

import fcntl
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ANALYTICS_FILE = Path(__file__).parent / "queries.json"


def log_query(session_id: str, query: str, response_preview: str = "") -> None:
    """
    Log a user query for analytics.

    Args:
        session_id: Session identifier (anonymized)
        query: User's question
        response_preview: First 100 chars of response (optional)
    """
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "session_id": session_id,
        "query": query,
        "response_preview": response_preview[:100] if response_preview else ""
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

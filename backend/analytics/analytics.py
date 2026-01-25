"""
Analytics logging for user queries.

PRIVACY NOTE: This file creates queries.json which contains user questions.
The queries.json file is gitignored to protect user privacy.
"""

import json
from datetime import datetime
from pathlib import Path

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

    # Append to file (one JSON object per line)
    try:
        with open(ANALYTICS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        # Don't crash the app if logging fails
        print(f"Warning: Failed to log query: {e}")


def get_recent_queries(limit: int = 20) -> list[dict]:
    """
    Get the most recent queries from the log.

    Args:
        limit: Number of recent queries to return

    Returns:
        List of query dictionaries
    """
    if not ANALYTICS_FILE.exists():
        return []

    queries = []
    with open(ANALYTICS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                queries.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue

    return queries[-limit:]


def get_query_count() -> int:
    """Get total number of logged queries."""
    if not ANALYTICS_FILE.exists():
        return 0

    with open(ANALYTICS_FILE, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)

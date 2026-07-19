from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BASE_DIR / "data"


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    anthropic_model: str
    anthropic_max_tokens: int
    environment: str
    data_dir: Path

    # Model routing: simple factual queries go to a faster/cheaper model,
    # everything else stays on anthropic_model. The router itself uses a
    # small classifier model.
    anthropic_model_simple: str = "claude-sonnet-5"
    anthropic_router_model: str = "claude-haiku-4-5-20251001"

    # Scalability settings (configurable via environment variables)
    rate_limit_requests_per_minute: int = 20  # Max requests per session per minute
    session_max_age_seconds: int = 3600  # 1 hour - sessions older than this are cleaned up
    api_timeout_seconds: float = 30.0  # Anthropic API timeout in seconds
    max_user_message_chars: int = 2000  # Prevent token exhaustion / abuse
    admin_token: str = ""  # Protect admin endpoints when set (recommended in prod)
    redis_url: str = ""  # Shared session store for multi-instance deployments
    trust_proxy_headers: bool = False  # Trust X-Forwarded-For only behind a safe proxy

    # Chat limit protection
    chat_password: str = ""  # Password to unlock unlimited chat access
    free_chat_limit: int = 2  # Number of exchanges before requiring password
    daily_conversation_limit: int = 200  # Global model-call budget per day (all visitors)

    # JD fit analysis ("Paste a job description")
    max_jd_chars: int = 15000  # Job descriptions are much longer than chat messages
    jd_daily_limit: int = 1  # Free analyses per visitor per day; password unlocks more

    # Server-owned visitor identity (quota/unlock key; session_id is history-only)
    visitor_cookie_name: str = "resume_assistant_visitor_id"
    visitor_ttl_seconds: int = 2592000  # 30 days
    session_hash_secret: str = ""  # HMAC key for anonymized analytics ids

    # RAG settings (Phase 3)
    openai_api_key: str = ""  # For embeddings
    qdrant_url: str | None = None  # Required when USE_RAG=true
    qdrant_api_key: str = ""  # Qdrant Cloud API key (optional, depending on cluster)
    use_rag: bool = True  # Enable RAG retrieval (vs static context)


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _to_int(value: str | None, default: int) -> int:
    """Parse int from env var with fallback to default on invalid input."""
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        import logging
        logging.getLogger(__name__).warning(
            f"Invalid int value '{value}', using default: {default}"
        )
        return default


def _to_float(value: str | None, default: float) -> float:
    """Parse float from env var with fallback to default on invalid input."""
    if value is None:
        return default
    try:
        return float(value.strip())
    except ValueError:
        import logging
        logging.getLogger(__name__).warning(
            f"Invalid float value '{value}', using default: {default}"
        )
        return default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    data_dir = Path(
        os.getenv(
            "DATA_DIR",
            DEFAULT_DATA_DIR,
        )
    )
    return Settings(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        anthropic_model=os.getenv(
            "ANTHROPIC_MODEL",
            "claude-opus-4-8",
        ),
        anthropic_max_tokens=_to_int(os.getenv("ANTHROPIC_MAX_TOKENS"), 1024),
        anthropic_model_simple=os.getenv(
            "ANTHROPIC_MODEL_SIMPLE",
            "claude-sonnet-5",
        ),
        anthropic_router_model=os.getenv(
            "ANTHROPIC_ROUTER_MODEL",
            "claude-haiku-4-5-20251001",
        ),
        environment=os.getenv("ENVIRONMENT", "development"),
        data_dir=data_dir,
        # Scalability settings (use defaults if not set)
        rate_limit_requests_per_minute=_to_int(
            os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE"), 20
        ),
        session_max_age_seconds=_to_int(os.getenv("SESSION_MAX_AGE_SECONDS"), 3600),
        api_timeout_seconds=_to_float(os.getenv("API_TIMEOUT_SECONDS"), 30.0),
        max_user_message_chars=_to_int(os.getenv("MAX_USER_MESSAGE_CHARS"), 2000),
        admin_token=os.getenv("ADMIN_TOKEN", ""),
        redis_url=os.getenv("REDIS_URL", ""),
        trust_proxy_headers=_to_bool(os.getenv("TRUST_PROXY_HEADERS"), default=False),
        # Chat limit protection
        chat_password=os.getenv("CHAT_PASSWORD", ""),
        free_chat_limit=_to_int(os.getenv("FREE_CHAT_LIMIT"), 2),
        daily_conversation_limit=_to_int(os.getenv("DAILY_CONVERSATION_LIMIT"), 200),
        max_jd_chars=_to_int(os.getenv("MAX_JD_CHARS"), 15000),
        jd_daily_limit=_to_int(os.getenv("JD_DAILY_LIMIT"), 1),
        visitor_cookie_name=os.getenv("VISITOR_COOKIE_NAME", "resume_assistant_visitor_id"),
        visitor_ttl_seconds=_to_int(os.getenv("VISITOR_TTL_SECONDS"), 2592000),
        # Unset in production breaks analytics-id correlation across restarts;
        # a random per-process secret still keeps raw session ids out of logs.
        session_hash_secret=os.getenv("SESSION_HASH_SECRET") or secrets.token_hex(16),
        # RAG settings
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        qdrant_url=os.getenv("QDRANT_URL"),
        qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
        use_rag=_to_bool(os.getenv("USE_RAG", "true"), default=True),
    )

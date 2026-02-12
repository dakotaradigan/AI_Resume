from __future__ import annotations

import os
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
    debug: bool
    data_dir: Path

    # Scalability settings (configurable via environment variables)
    rate_limit_requests_per_minute: int = 20  # Max requests per session per minute
    session_max_age_seconds: int = 3600  # 1 hour - sessions older than this are cleaned up
    api_timeout_seconds: float = 30.0  # Anthropic API timeout in seconds
    max_user_message_chars: int = 2000  # Prevent token exhaustion / abuse
    admin_token: str = ""  # Protect admin endpoints when set (recommended in prod)

    # Chat limit protection
    chat_password: str = ""  # Password to unlock unlimited chat access
    free_chat_limit: int = 2  # Number of exchanges before requiring password

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
            "claude-opus-4-5-20251101",
        ),
        anthropic_max_tokens=_to_int(os.getenv("ANTHROPIC_MAX_TOKENS"), 1024),
        environment=os.getenv("ENVIRONMENT", "development"),
        debug=_to_bool(os.getenv("DEBUG"), default=False),
        data_dir=data_dir,
        # Scalability settings (use defaults if not set)
        rate_limit_requests_per_minute=_to_int(
            os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE"), 20
        ),
        session_max_age_seconds=_to_int(os.getenv("SESSION_MAX_AGE_SECONDS"), 3600),
        api_timeout_seconds=_to_float(os.getenv("API_TIMEOUT_SECONDS"), 30.0),
        max_user_message_chars=_to_int(os.getenv("MAX_USER_MESSAGE_CHARS"), 2000),
        admin_token=os.getenv("ADMIN_TOKEN", ""),
        # Chat limit protection
        chat_password=os.getenv("CHAT_PASSWORD", ""),
        free_chat_limit=_to_int(os.getenv("FREE_CHAT_LIMIT"), 2),
        # RAG settings
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        qdrant_url=os.getenv("QDRANT_URL"),
        qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
        use_rag=_to_bool(os.getenv("USE_RAG", "true"), default=True),
    )


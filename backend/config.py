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

    # RAG settings (Phase 3)
    openai_api_key: str = ""  # For embeddings
    qdrant_url: str | None = None  # Required when USE_RAG=true
    qdrant_api_key: str = ""  # Qdrant Cloud API key (optional, depending on cluster)
    use_rag: bool = True  # Enable RAG retrieval (vs static context)


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
        anthropic_max_tokens=int(os.getenv("ANTHROPIC_MAX_TOKENS", "2048")),
        environment=os.getenv("ENVIRONMENT", "development"),
        debug=_to_bool(os.getenv("DEBUG"), default=False),
        data_dir=data_dir,
        # Scalability settings (use defaults if not set)
        rate_limit_requests_per_minute=int(
            os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "20")
        ),
        session_max_age_seconds=int(os.getenv("SESSION_MAX_AGE_SECONDS", "3600")),
        api_timeout_seconds=float(os.getenv("API_TIMEOUT_SECONDS", "30.0")),
        max_user_message_chars=int(os.getenv("MAX_USER_MESSAGE_CHARS", "2000")),
        admin_token=os.getenv("ADMIN_TOKEN", ""),
        # RAG settings
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        qdrant_url=os.getenv("QDRANT_URL"),
        qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
        use_rag=_to_bool(os.getenv("USE_RAG", "true"), default=True),
    )


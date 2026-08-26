"""
Centralized application configuration.

All environment-variable access should go through this module so that
defaults, parsing, and validation live in exactly one place.
"""
from __future__ import annotations

import logging
import os
import secrets
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer for %s=%r, using default %s", name, raw, default)
        return default


class Settings:
    """Application settings, resolved once at import time."""

    # ── Environment ──────────────────────────────────────────────────────
    ENV: str = os.environ.get("ENV", "development")
    IS_PRODUCTION: bool = ENV.lower() in {"production", "prod"}

    # ── CORS ─────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = _split_csv(
        os.environ.get(
            "ALLOWED_ORIGINS",
            "http://localhost:3000,http://localhost:5173,"
            "https://siratsync-ai-agent.onrender.com,https://siratsync.in",
        )
    )

    # ── Groq / LLM ───────────────────────────────────────────────────────
    GROQ_API_KEY: str | None = os.environ.get("GROQ_API_KEY")
    GROQ_MODEL: str = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
    LLM_TIMEOUT_SECONDS: float = float(os.environ.get("LLM_TIMEOUT_SECONDS", "20"))
    LLM_MAX_RETRIES: int = _env_int("LLM_MAX_RETRIES", 2)

    # ── Redis ────────────────────────────────────────────────────────────
    REDIS_URL: str | None = os.environ.get("REDIS_URL")
    UPSTASH_REDIS_HOST: str | None = os.environ.get("UPSTASH_REDIS_HOST")
    UPSTASH_REDIS_PASSWORD: str | None = os.environ.get("UPSTASH_REDIS_PASSWORD")
    UPSTASH_REDIS_PORT: int = _env_int("UPSTASH_REDIS_PORT", 6379)
    REDIS_SOCKET_TIMEOUT: float = float(os.environ.get("REDIS_SOCKET_TIMEOUT", "3"))
    REDIS_MAX_CONNECTIONS: int = _env_int("REDIS_MAX_CONNECTIONS", 20)

    # ── Rate limiting ────────────────────────────────────────────────────
    RATE_LIMIT_MAX_KEYS: int = _env_int("RATE_LIMIT_MAX_KEYS", 10_000)
    RATE_LIMIT_RPM: int = _env_int("RATE_LIMIT_RPM", 60)
    # Falls back to in-process limiting only when Redis is unavailable.
    RATE_LIMIT_FAIL_OPEN: bool = _env_bool("RATE_LIMIT_FAIL_OPEN", True)

    # ── Cache ────────────────────────────────────────────────────────────
    SUMMARY_CACHE_PREFIX: str = "summarize:"
    RESPONSE_CACHE_PREFIX: str = "cache:"
    RESPONSE_CACHE_TTL_MINUTES: int = _env_int("RESPONSE_CACHE_TTL_MINUTES", 60)
    LOCAL_CACHE_MAX_ENTRIES: int = _env_int("LOCAL_CACHE_MAX_ENTRIES", 2_000)

    # ── Auth ─────────────────────────────────────────────────────────────
    # Used to authorize access to per-user endpoints (GET/DELETE /user/{id}).
    # If unset in production, a random key is generated at boot (logged as a
    # warning) so the service never silently runs wide open; set INTERNAL_API_KEY
    # explicitly so restarts don't invalidate previously issued keys.
    INTERNAL_API_KEY: str = os.environ.get("INTERNAL_API_KEY") or secrets.token_urlsafe(32)
    REQUIRE_USER_AUTH: bool = _env_bool("REQUIRE_USER_AUTH", True)

    # ── Request limits ───────────────────────────────────────────────────
    MAX_MESSAGE_LENGTH: int = _env_int("MAX_MESSAGE_LENGTH", 2000)
    MAX_CONTEXT_LENGTH: int = _env_int("MAX_CONTEXT_LENGTH", 4000)
    MAX_USER_ID_LENGTH: int = _env_int("MAX_USER_ID_LENGTH", 128)
    MAX_POST_CONTENT_LENGTH: int = _env_int("MAX_POST_CONTENT_LENGTH", 5000)

    # ── WhatsApp ─────────────────────────────────────────────────────────
    WHATSAPP_TOKEN: str = os.environ.get("WHATSAPP_TOKEN", "")
    WHATSAPP_PHONE_NUMBER_ID: str = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
    WHATSAPP_VERIFY_TOKEN: str = os.environ.get("WHATSAPP_VERIFY_TOKEN", "siratsync_secret")
    WHATSAPP_APP_SECRET: str = os.environ.get("WHATSAPP_APP_SECRET", "")
    WHATSAPP_API_VERSION: str = os.environ.get("WHATSAPP_API_VERSION", "v19.0")

    # ── Render / keep-alive ──────────────────────────────────────────────
    RENDER_URL: str = os.environ.get("RENDER_URL", "https://siratsync-api.onrender.com/health")
    KEEP_ALIVE_ENABLED: bool = _env_bool("RENDER", False) or _env_bool("KEEP_ALIVE", False)

    def validate(self) -> None:
        """Fail fast on missing required configuration."""
        if not self.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is required")

        if not os.environ.get("INTERNAL_API_KEY"):
            if self.IS_PRODUCTION:
                logger.warning(
                    "INTERNAL_API_KEY is not set. A random key was generated for this "
                    "process only, which means it will change on every restart and "
                    "won't be shared across multiple instances. Set INTERNAL_API_KEY "
                    "explicitly in production."
                )
            else:
                logger.info(
                    "INTERNAL_API_KEY not set — using an ephemeral dev key. "
                    "Set INTERNAL_API_KEY for stable auth across restarts."
                )

        if self.IS_PRODUCTION and "*" in self.ALLOWED_ORIGINS:
            logger.warning("ALLOWED_ORIGINS includes '*' in production — this is unsafe.")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# ── Backwards-compatible module-level constants ─────────────────────────
# Kept so existing `from app.core.config import X` imports continue to work.
ALLOWED_ORIGINS = settings.ALLOWED_ORIGINS
GROQ_API_KEY = settings.GROQ_API_KEY
RATE_LIMIT_MAX_KEYS = settings.RATE_LIMIT_MAX_KEYS
RATE_LIMIT_RPM = settings.RATE_LIMIT_RPM
SUMMARY_CACHE_PREFIX = settings.SUMMARY_CACHE_PREFIX

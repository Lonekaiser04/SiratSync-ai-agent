"""
Security utilities: request authentication and prompt-injection mitigation.
"""
from __future__ import annotations

import hmac
import logging
import re

from fastapi import Header, HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Internal API auth ────────────────────────────────────────────────────
async def require_internal_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """
    FastAPI dependency that protects endpoints exposing per-user data
    (profile reads, session deletion) from unauthenticated access.

    Uses a constant-time comparison to avoid timing side-channels.
    Controlled by REQUIRE_USER_AUTH so local development can opt out
    explicitly without weakening the production default.
    """
    if not settings.REQUIRE_USER_AUTH:
        return

    if not x_api_key or not hmac.compare_digest(x_api_key, settings.INTERNAL_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key.",
        )


# ── Prompt-injection mitigation ──────────────────────────────────────────
# These patterns catch common attempts to override the system prompt via
# user-supplied `message` / `context` fields. This is a defense-in-depth
# heuristic, not a guarantee — the system prompt's boundaries section and
# output-side checks remain the primary safeguards.
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore (all |any )?(previous|prior|above|earlier) instructions", re.I),
    re.compile(r"disregard (all |any )?(previous|prior|above|earlier)", re.I),
    re.compile(r"you are now (a|an)\b", re.I),
    re.compile(r"forget (your|all|previous) (instructions|rules|prompt)", re.I),
    re.compile(r"system\s*prompt", re.I),
    re.compile(r"reveal (your|the) (system )?prompt", re.I),
    re.compile(r"act as (if|though)", re.I),
    re.compile(r"new instructions?:", re.I),
    re.compile(r"\bDAN\b|developer mode|jailbreak", re.I),
    re.compile(r"</?(system|assistant|user)>", re.I),
    re.compile(r"\[/?(system|assistant|user)]", re.I),
]


def detect_prompt_injection(text: str) -> bool:
    """Best-effort heuristic flag for likely prompt-injection attempts."""
    if not text:
        return False
    return any(p.search(text) for p in _INJECTION_PATTERNS)


def sanitize_user_text(text: str, *, max_length: int) -> str:
    """
    Defensive cleanup applied to any user-supplied text before it is
    interpolated into an LLM prompt:
      - hard length cap (defense in depth on top of Pydantic validation)
      - strips role-delimiter-like tokens that could confuse chat templates
      - collapses excessive whitespace/control characters
    """
    if not text:
        return text

    text = text[:max_length]
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)  # control chars
    text = re.sub(r"</?(system|assistant|user)>", "", text, flags=re.I)
    text = re.sub(r"\[/?(system|assistant|user)]", "", text, flags=re.I)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()

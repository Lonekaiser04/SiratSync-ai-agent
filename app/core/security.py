"""
Security utilities: request authentication and prompt-injection mitigation.
"""
from __future__ import annotations

import hmac
import logging
import os
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


# ── Firebase Authentication ──────────────────────────────────────────────
_firebase_app = None


def get_firebase_app():
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app

    try:
        import firebase_admin
        from firebase_admin import credentials

        cred_json = getattr(settings, "FIREBASE_CREDENTIALS_JSON", None) or os.environ.get("FIREBASE_CREDENTIALS_JSON")
        if cred_json:
            try:
                import json
                cred_dict = json.loads(cred_json)
                cred = credentials.Certificate(cred_dict)
                _firebase_app = firebase_admin.initialize_app(cred, name="siratsync-auth")
            except Exception as e:
                logger.warning("Could not initialize Firebase Admin from credentials JSON: %s", e)
        elif not firebase_admin._apps:
            try:
                _firebase_app = firebase_admin.initialize_app()
            except Exception:
                pass
        else:
            _firebase_app = firebase_admin.get_app()
    except ImportError:
        logger.warning("firebase_admin package not installed — Firebase token verification unavailable")
    except Exception as e:
        logger.warning("Unexpected error initializing Firebase Admin: %s", e)

    return _firebase_app


def verify_firebase_token(auth_header: str | None) -> str | None:
    """
    Verifies a Firebase ID token from the 'Authorization: Bearer <token>' header.
    Returns the verified uid if valid, None otherwise.
    """
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return None

    app = get_firebase_app()
    if not app:
        return None

    try:
        from firebase_admin import auth as firebase_auth
        decoded = firebase_auth.verify_id_token(token, app=app)
        return decoded.get("uid")
    except Exception as e:
        logger.debug("Firebase token verification failed: %s", e)
        return None


# ── Client IP Resolution (Reverse Proxy Safe) ─────────────────────────────
def get_client_ip(request) -> str:
    """
    Safely extract the real client IP address behind reverse proxies (Render, Cloudflare, etc.).
    Extracts the leftmost public IP from X-Forwarded-For, or falls back to client host.
    """
    import ipaddress

    forwarded_for = request.headers.get("X-Forwarded-For") or request.headers.get("x-forwarded-for")
    if forwarded_for:
        parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
        for part in parts:
            try:
                ip = ipaddress.ip_address(part)
                if not ip.is_private and not ip.is_loopback:
                    return part
            except ValueError:
                continue
        if parts:
            return parts[0]

    if hasattr(request, "client") and request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"



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

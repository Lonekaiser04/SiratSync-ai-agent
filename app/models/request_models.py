"""
Pydantic request models with Pydantic v2 validators and defensive
edge-case handling (empty strings, whitespace-only input, control chars).
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _strip_control_chars(value: str) -> str:
    return _CONTROL_CHARS_RE.sub("", value)


class ChatRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=settings.MAX_USER_ID_LENGTH)
    message: str = Field(..., min_length=1, max_length=settings.MAX_MESSAGE_LENGTH)
    user_name: str | None = Field(default=None, max_length=200)
    app_version: str | None = Field(default="2.0", max_length=20)
    context: str | None = Field(default=None)
    user_timezone: str | None = Field(
        default=None,
        max_length=64,
        description="IANA timezone name (e.g. 'Asia/Karachi'), used for time-of-day "
        "suggestions like morning/evening adhkar. Defaults to UTC if omitted.",
    )

    @field_validator("user_timezone")
    @classmethod
    def validate_timezone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(v)  # raises if unknown
        except Exception:
            return None  # silently ignore invalid tz rather than erroring the whole request
        return v

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        v = _strip_control_chars(v).strip()
        if not v:
            raise ValueError("message cannot be empty")
        if len(v) > settings.MAX_MESSAGE_LENGTH:
            raise ValueError(f"message too long (max {settings.MAX_MESSAGE_LENGTH} characters)")
        return v

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("user_id cannot be empty")
        if len(v) > settings.MAX_USER_ID_LENGTH:
            raise ValueError("invalid user_id: too long")
        # Guard against Redis key-injection via control/whitespace chars that
        # could smuggle extra ':'-delimited segments into our key namespace.
        if _CONTROL_CHARS_RE.search(v) or "\n" in v or "\r" in v:
            raise ValueError("invalid user_id: contains disallowed characters")
        return v

    @field_validator("user_name")
    @classmethod
    def validate_user_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = _strip_control_chars(v).strip()
        return v or None

    @field_validator("context")
    @classmethod
    def validate_context(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = _strip_control_chars(v).strip()
        if not v:
            return None
        if len(v) > settings.MAX_CONTEXT_LENGTH:
            return v[: settings.MAX_CONTEXT_LENGTH]
        return v


class SummarizeRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=settings.MAX_USER_ID_LENGTH)
    post_content: str = Field(..., min_length=1, max_length=settings.MAX_POST_CONTENT_LENGTH)

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("user_id cannot be empty")
        if len(v) > settings.MAX_USER_ID_LENGTH:
            raise ValueError("invalid user_id: too long")
        return v

    @field_validator("post_content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        v = _strip_control_chars(v).strip()
        if not v:
            raise ValueError("post_content cannot be empty")
        if len(v) > settings.MAX_POST_CONTENT_LENGTH:
            raise ValueError(
                f"post_content too long (max {settings.MAX_POST_CONTENT_LENGTH} characters)"
            )
        return v

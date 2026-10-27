"""
Unified LLM Service for SiratSync AI Assistant.

Provides centralized model execution with:
- Configurable primary and fallback models from environment variables.
- Strict error classification (retrying only for model-not-found, timeouts,
  rate limits, and transient provider 5xx errors; failing fast for client 4xx errors).
- Transparent logging and explicit reporting of whether fallback was used.
- Full compatibility with existing synchronous and asynchronous callers.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncGroq,
    AuthenticationError,
    BadRequestError,
    Groq,
    GroqError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Standardized result object for all LLM completions."""

    content: str
    model_used: str
    is_fallback: bool
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


def is_retryable_provider_error(exc: Exception) -> bool:
    """
    Determines whether an exception warrants model fallback or bounded retry.

    Retryable:
      - NotFoundError (404: model deprecated, decommissioned, or mistyped)
      - RateLimitError (429: provider rate quota exceeded)
      - APITimeoutError (provider timed out)
      - APIConnectionError (network failure / connection dropped)
      - InternalServerError (500: Groq upstream error)
      - APIStatusError with status code in {404, 429, 500, 502, 503, 504}

    Non-retryable (fail fast):
      - BadRequestError (400: invalid prompt parameters, malformed request)
      - AuthenticationError (401: bad API key)
      - PermissionDeniedError (403: unauthorized)
      - UnprocessableEntityError (422: schema mismatch)
    """
    if isinstance(
        exc,
        (
            BadRequestError,
            AuthenticationError,
            PermissionDeniedError,
            UnprocessableEntityError,
        ),
    ):
        return False

    if isinstance(
        exc,
        (
            NotFoundError,
            RateLimitError,
            APITimeoutError,
            APIConnectionError,
            InternalServerError,
        ),
    ):
        return True

    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        if status_code in (404, 429, 500, 502, 503, 504):
            return True
        if 400 <= status_code < 500:
            return False

    msg = str(exc).lower()
    retry_indicators = (
        "timeout",
        "timed out",
        "connection",
        "rate limit",
        "rate_limit",
        "503",
        "502",
        "504",
        "500",
        "model_not_found",
        "does not exist",
    )
    if any(ind in msg for ind in retry_indicators):
        return True

    return isinstance(exc, GroqError)


class LLMService:
    """Manages asynchronous LLM invocations with robust fallback."""

    def __init__(self, async_client: AsyncGroq | None = None) -> None:
        self._async_client = async_client

    @property
    def client(self) -> AsyncGroq:
        if self._async_client is None:
            self._async_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        return self._async_client

    async def generate_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.5,
        max_tokens: int = 1500,
        primary_model: str | None = None,
        fallback_model: str | None = None,
        timeout: float | None = None,
        client: AsyncGroq | None = None,
        request_id: str = "internal",
    ) -> LLMResponse:
        """
        Executes a chat completion using the primary model.
        On appropriate retryable errors, falls back to the configured fallback model.

        Never reports a fallback response as a successful primary-model response.
        Fails fast on non-retryable 4xx client errors without attempting fallback.
        """
        effective_client = client or self.client
        primary = primary_model or settings.GROQ_MODEL
        fallback = fallback_model or settings.FALLBACK_GROQ_MODEL
        call_timeout = timeout or settings.LLM_TIMEOUT_SECONDS

        try:
            raw_response = await effective_client.chat.completions.create(
                model=primary,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=call_timeout,
            )
            content = (raw_response.choices[0].message.content or "").strip()
            usage = getattr(raw_response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
            completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
            total_tokens = getattr(usage, "total_tokens", 0) if usage else 0
            finish_reason = getattr(raw_response.choices[0], "finish_reason", "stop") or "stop"

            logger.info(
                "request_id=%s LLM reply generated successfully (%d chars) using model %s",
                request_id,
                len(content),
                primary,
            )
            return LLMResponse(
                content=content,
                model_used=primary,
                is_fallback=False,
                finish_reason=finish_reason,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )

        except Exception as exc:
            if not is_retryable_provider_error(exc) or primary == fallback:
                logger.error(
                    "request_id=%s LLM error with model %s (non-retryable or no alternative): %s",
                    request_id,
                    primary,
                    exc,
                )
                raise

            logger.warning(
                "request_id=%s Primary model %s failed (%s: %s). Falling back to %s",
                request_id,
                primary,
                type(exc).__name__,
                exc,
                fallback,
            )

            fallback_response = await effective_client.chat.completions.create(
                model=fallback,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=call_timeout,
            )
            content = (fallback_response.choices[0].message.content or "").strip()
            usage = getattr(fallback_response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
            completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
            total_tokens = getattr(usage, "total_tokens", 0) if usage else 0
            finish_reason = getattr(fallback_response.choices[0], "finish_reason", "stop") or "stop"

            logger.info(
                "request_id=%s LLM reply generated successfully (%d chars) using fallback model %s",
                request_id,
                len(content),
                fallback,
            )
            return LLMResponse(
                content=content,
                model_used=fallback,
                is_fallback=True,
                finish_reason=finish_reason,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )


llm_service = LLMService()

# ── Backwards-compatible synchronous helpers ─────────────────────────────────
llm = Groq(api_key=os.environ.get("GROQ_API_KEY")) if os.environ.get("GROQ_API_KEY") else None


def _extract_english_only(rag_data: str) -> str:
    """Extract English-only lines from retrieved RAG reference blocks."""
    english_lines = []
    for line in rag_data.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("VERSE REFERENCE:"):
            english_lines.append(stripped)
        elif stripped.startswith("ENGLISH:"):
            text = stripped.replace("ENGLISH:", "").strip()
            if text.startswith("_") and text.endswith("_"):
                text = text[1:-1]
            english_lines.append(text)
        elif stripped.startswith(
            (
                "SUMMARY:",
                "MAIN TOPICS:",
                "SURAH:",
                "SURAH NUMBER:",
                "VERSES:",
                "REVELATION TYPE:",
                "JUZ:",
                "SIMILAR VERSES:",
                "  -",
            )
        ):
            english_lines.append(stripped)

    return "\n".join(english_lines)


def _format_rag_data_direct(rag_data: str) -> str:
    """Deterministic fallback formatter when LLM call fails completely."""
    lines_out = ["📖 **Quranic Guidance:**\n"]
    for line in rag_data.split("\n"):
        stripped = line.strip()
        if not stripped:
            lines_out.append("")
            continue
        if stripped.startswith("VERSE REFERENCE:"):
            ref = stripped.replace("VERSE REFERENCE:", "").strip()
            lines_out.append(f"\n**📍 {ref}**")
        elif stripped.startswith("SURAH:"):
            lines_out.append(f"\n**{stripped.replace('SURAH:', '📖').strip()}**")
        elif stripped.startswith("ARABIC:"):
            lines_out.append(f" {stripped.replace('ARABIC:', '').strip()}")
        elif stripped.startswith("ENGLISH:"):
            lines_out.append(f"{stripped.replace('ENGLISH:', '').strip()}_")
        elif stripped.startswith("URDU:"):
            lines_out.append(f"{stripped.replace('URDU:', '').strip()}")
        elif stripped.startswith("KASHMIRI TAFSIR:") or stripped.startswith("KASHMIRI:"):
            ks = re.sub(r"^KASHMIRI( TAFSIR)?:", "", stripped).strip()
            lines_out.append(f"**Kashmiri:** {ks}")
        elif stripped.startswith("TRANSLITERATION:"):
            lines_out.append(f"_{stripped.replace('TRANSLITERATION:', '').strip()}_")
        elif stripped.startswith("SUMMARY:"):
            lines_out.append(f"📝 {stripped.replace('SUMMARY:', '').strip()}")
        elif stripped.startswith("MAIN TOPICS:"):
            lines_out.append(f"📌 **Topics:** {stripped.replace('MAIN TOPICS:', '').strip()}")
        elif stripped.startswith("VERSES:"):
            lines_out.append(f"📊 {stripped}")
        elif stripped.startswith("SIMILAR VERSES:"):
            lines_out.append("\n📎 **Similar Verses:**")
        elif stripped.startswith("  -"):
            lines_out.append(stripped)
        elif stripped.startswith("RELATED SURAHS:"):
            lines_out.append("\n📖 **Related Surahs:**")
        elif stripped.startswith("  -") or stripped.startswith("VERSE:"):
            lines_out.append(stripped.replace("VERSE:", "\n**Verse:**"))
        else:
            lines_out.append(stripped)

    return "\n".join(lines_out)


def _call_llm_with_rag(user_query: str, rag_data: str, user_profile: dict) -> str:
    """Synchronous legacy wrapper for RAG English completion."""
    english_only = _extract_english_only(rag_data)
    if not english_only.strip():
        return "I couldn't find relevant information in English."

    if llm is None:
        return _format_rag_data_direct(rag_data)

    try:
        response = llm.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are SiratSync AI, an Islamic assistant.\n"
                        "You will receive Quran reference data in English only.\n"
                        "1. Answer using provided data strictly.\n"
                        "2. Reference verses properly (e.g. 'Surah Al-Baqarah 2:255').\n"
                        "3. Keep explanations clear and concise.\n"
                        "4. Never fabricate citations or attempt non-English text.\n"
                        "5. End with: '📌 For accurate verse details, ask by reference (e.g., 94:5).'"
                    ),
                },
                {
                    "role": "user",
                    "content": f"Based on this information:\n\n{english_only}\n\nUser asks: {user_query}\n\nProvide a helpful English response:",
                },
            ],
            temperature=0.3,
            max_tokens=600,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("Legacy sync LLM failed: %s", e)
        return _format_rag_data_direct(rag_data)
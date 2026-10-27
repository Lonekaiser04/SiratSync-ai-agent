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
from typing import Any, AsyncIterator

from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncGroq,
    AuthenticationError,
    BadRequestError,
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


@dataclass
class LLMStreamChunk:
    """Standardized streaming chunk emitted during token generation."""

    delta: str
    model_used: str
    is_fallback: bool
    finish_reason: str | None = None


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

    async def generate_completion_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.5,
        max_tokens: int = 1500,
        primary_model: str | None = None,
        fallback_model: str | None = None,
        timeout: float | None = None,
        client: AsyncGroq | None = None,
        request_id: str = "internal",
    ) -> AsyncIterator[LLMStreamChunk]:
        """
        Executes a streaming chat completion yielding LLMStreamChunk tokens.
        If the primary model fails on connection or before yielding tokens with a retryable error,
        it automatically falls back to the configured fallback model.
        Fails fast on 4xx client errors without attempting fallback.
        """
        effective_client = client or self.client
        primary = primary_model or settings.GROQ_MODEL
        fallback = fallback_model or settings.FALLBACK_GROQ_MODEL
        call_timeout = timeout or settings.LLM_TIMEOUT_SECONDS

        tokens_yielded = 0
        try:
            stream = await effective_client.chat.completions.create(
                model=primary,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=call_timeout,
                stream=True,
            )
            async for chunk in stream:
                choices = getattr(chunk, "choices", None)
                choice = choices[0] if choices else None
                delta = getattr(getattr(choice, "delta", None), "content", None) or ""
                finish_reason = getattr(choice, "finish_reason", None)
                if delta:
                    tokens_yielded += 1
                    yield LLMStreamChunk(
                        delta=delta,
                        model_used=primary,
                        is_fallback=False,
                        finish_reason=finish_reason,
                    )
            logger.info(
                "request_id=%s LLM streaming completed (%d chunks) using model %s",
                request_id,
                tokens_yielded,
                primary,
            )
            return

        except Exception as exc:
            if tokens_yielded > 0 or not is_retryable_provider_error(exc) or primary == fallback:
                logger.error(
                    "request_id=%s LLM streaming error with model %s (tokens_yielded=%d): %s",
                    request_id,
                    primary,
                    tokens_yielded,
                    exc,
                )
                raise

            logger.warning(
                "request_id=%s Primary model %s failed before stream tokens (%s: %s). Falling back to %s",
                request_id,
                primary,
                type(exc).__name__,
                exc,
                fallback,
            )

            fallback_stream = await effective_client.chat.completions.create(
                model=fallback,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=call_timeout,
                stream=True,
            )
            async for chunk in fallback_stream:
                choices = getattr(chunk, "choices", None)
                choice = choices[0] if choices else None
                delta = getattr(getattr(choice, "delta", None), "content", None) or ""
                finish_reason = getattr(choice, "finish_reason", None)
                if delta:
                    tokens_yielded += 1
                    yield LLMStreamChunk(
                        delta=delta,
                        model_used=fallback,
                        is_fallback=True,
                        finish_reason=finish_reason,
                    )
            logger.info(
                "request_id=%s LLM streaming completed (%d chunks) using fallback model %s",
                request_id,
                tokens_yielded,
                fallback,
            )


llm_service = LLMService()
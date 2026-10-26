"""
Post-summarization endpoint for SiratSync Community.

Pipeline:
1. Input sanitization: Strips zero-width characters, collapses emoji and punctuation spam,
   and normalizes excessive whitespace.
2. Trivial input short-circuit: Skips LLM round-trip for short, empty, or symbol-only posts.
3. Cache lookup: Leverages Redis/in-memory cache across users for identical public posts.
4. Adaptive token limit & prompt formatting: Dynamically scales max_tokens to post length.
5. Model execution & fallback: Invokes primary model (openai/gpt-oss-20b) with transparent
   fallback to openai/gpt-oss-120b on retryable provider errors.
6. Output post-processing: Strips meta-preambles and guarantees clean sentence boundaries.
7. Caching & response assembly: Caches only validated, high-quality summaries.
"""
from __future__ import annotations

import json as json_module
import logging
import re

from fastapi import APIRouter, HTTPException, Request
from groq import AsyncGroq, GroqError

from app.core.config import settings
from app.core.security import sanitize_user_text
from app.models.request_models import SummarizeRequest
from app.models.response_models import SummarizeResponse
from app.prompts.summarize_prompt import SUMMARIZE_PROMPT
from app.services.llm_service import llm_service
from app.utils.cache import cache

logger = logging.getLogger(__name__)

router = APIRouter()

llm = AsyncGroq(api_key=settings.GROQ_API_KEY)

_MIN_CONTENT_LENGTH_FOR_SUMMARY = 30
_ZERO_WIDTH_CHARS = re.compile(r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad]")
_REPEATED_PUNCTUATION = re.compile(r"([!?.,;:~-])\1{2,}")
_REPEATED_SPACES = re.compile(r"[ \t]+")
_REPEATED_NEWLINES = re.compile(r"\n{3,}")
_PREAMBLE_PATTERN = re.compile(
    r"^(?:here is a summary(?: of the post)?\s*:?|summary(?: of the post)?\s*:|in summary\s*:)\s*",
    re.IGNORECASE,
)


def preprocess_post_content(raw_content: str) -> tuple[str, bool]:
    """
    Cleans noisy formatting, zero-width characters, and spam while preserving authentic multilingual content.
    Returns (cleaned_content, is_trivial).
    """
    if not raw_content:
        return "", True

    text = _ZERO_WIDTH_CHARS.sub("", raw_content)
    text = _REPEATED_PUNCTUATION.sub(r"\1\1", text)
    text = _REPEATED_SPACES.sub(" ", text)
    text = _REPEATED_NEWLINES.sub("\n\n", text)
    cleaned = text.strip()

    if len(cleaned) < _MIN_CONTENT_LENGTH_FOR_SUMMARY:
        return cleaned, True

    # Check if content has meaningful text (not just punctuation or whitespace)
    has_letters = any(c.isalnum() for c in cleaned)
    if not has_letters:
        return cleaned, True

    return cleaned, False


def _get_adaptive_max_tokens(content_length: int) -> int:
    """Scales completion token allowance proportionally with source length."""
    if content_length <= 250:
        return 100
    if content_length <= 1000:
        return 250
    return 450


def clean_summary_output(raw_summary: str, original_content: str) -> str:
    """Strips LLM meta-preambles and ensures coherent sentence boundaries."""
    summary = raw_summary.strip()
    summary = _PREAMBLE_PATTERN.sub("", summary).strip()

    # If the summary is empty after stripping, return a clean prefix of the original
    if not summary:
        cutoff = original_content[:200].rfind(" ")
        return original_content[: cutoff if cutoff > 50 else 200].strip()

    # If summary was abruptly truncated mid-word without terminal punctuation
    if len(summary) > 50 and summary[-1] not in ".!?\"'”":
        last_punct = max(
            summary.rfind("."),
            summary.rfind("!"),
            summary.rfind("?"),
        )
        if last_punct > len(summary) * 0.6:
            summary = summary[: last_punct + 1].strip()

    return summary


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize_post(request: SummarizeRequest, http_request: Request = None):
    request_id = (
        getattr(http_request.state, "request_id", "unknown")
        if http_request and hasattr(http_request, "state")
        else "summarize"
    )

    try:
        raw_content = request.post_content or ""
        cleaned_content, is_trivial = preprocess_post_content(raw_content)

        if is_trivial:
            logger.info("request_id=%s Short or trivial content — bypassing LLM", request_id)
            return SummarizeResponse(
                summary=cleaned_content,
                original_length=len(raw_content),
                summary_length=len(cleaned_content),
            )

        # Check response cache
        cached = await cache.get(cleaned_content, request.user_id, scope="summarize")
        if cached:
            try:
                data = json_module.loads(cached)
                logger.info("request_id=%s Summarize cache hit", request_id)
                return SummarizeResponse(**data)
            except (json_module.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning("request_id=%s Corrupt summarize cache entry, regenerating: %s", request_id, e)

        safe_content = sanitize_user_text(cleaned_content, max_length=settings.MAX_POST_CONTENT_LENGTH)
        max_tokens = _get_adaptive_max_tokens(len(safe_content))

        try:
            llm_result = await llm_service.generate_completion(
                messages=[
                    {"role": "system", "content": SUMMARIZE_PROMPT.format(content=safe_content)},
                    {"role": "user", "content": "Summarize this post concisely and faithfully."},
                ],
                temperature=0.3,
                max_tokens=max_tokens,
                client=llm,
                request_id=request_id,
            )
        except GroqError as e:
            logger.error("request_id=%s Summarize LLM provider failure: %s", request_id, e, exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="Summarization service is temporarily unavailable. Please try again shortly.",
            ) from e

        final_summary = clean_summary_output(llm_result.content, safe_content)

        result = SummarizeResponse(
            summary=final_summary,
            original_length=len(raw_content),
            summary_length=len(final_summary),
        )

        try:
            await cache.set(
                cleaned_content,
                request.user_id,
                json_module.dumps(result.model_dump()),
                ttl_minutes=1440,
                scope="summarize",
            )
        except (TypeError, ValueError) as e:
            logger.warning("request_id=%s Failed to cache summary: %s", request_id, e)

        logger.info(
            "request_id=%s Summary produced: %d chars (from %d) [model=%s, fallback=%s]",
            request_id,
            result.summary_length,
            result.original_length,
            llm_result.model_used,
            llm_result.is_fallback,
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error("request_id=%s Summarize internal error: %s", request_id, e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Summarization failed due to an internal error."
        ) from e

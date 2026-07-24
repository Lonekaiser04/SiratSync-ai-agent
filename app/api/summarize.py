"""
Post-summarization endpoint: shortens community-post text while preserving
sacred text verbatim (enforced by SUMMARIZE_PROMPT's explicit rules).
"""
import json as json_module
import logging

from fastapi import APIRouter, HTTPException
from groq import AsyncGroq, GroqError

from app.core.config import settings
from app.core.security import sanitize_user_text
from app.models.request_models import SummarizeRequest
from app.models.response_models import SummarizeResponse
from app.prompts.summarize_prompt import SUMMARIZE_PROMPT
from app.utils.cache import cache

logger = logging.getLogger(__name__)

router = APIRouter()

llm = AsyncGroq(api_key=settings.GROQ_API_KEY)

_MIN_CONTENT_LENGTH_FOR_SUMMARY = 30


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize_post(request: SummarizeRequest):
    try:
        content = request.post_content.strip()

        if len(content) < _MIN_CONTENT_LENGTH_FOR_SUMMARY:
            return SummarizeResponse(
                summary=content,
                original_length=len(content),
                summary_length=len(content),
            )

        cached = cache.get(content, request.user_id, scope="summarize")
        if cached:
            try:
                data = json_module.loads(cached)
                return SummarizeResponse(**data)
            except (json_module.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning("Corrupt summarize cache entry, regenerating: %s", e)

        safe_content = sanitize_user_text(content, max_length=settings.MAX_POST_CONTENT_LENGTH)

        try:
            llm_response = await llm.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SUMMARIZE_PROMPT.format(content=safe_content)},
                    {"role": "user", "content": "Summarize this post concisely"},
                ],
                temperature=0.3,
                max_tokens=150,
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
        except GroqError as e:
            logger.error("Summarize LLM call failed: %s", e, exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="Summarization service is temporarily unavailable. Please try again shortly.",
            ) from e

        raw_summary = llm_response.choices[0].message.content
        summary = raw_summary.strip() if raw_summary else content[:200]

        result = SummarizeResponse(
            summary=summary,
            original_length=len(content),
            summary_length=len(summary),
        )

        try:
            cache.set(
                content,
                request.user_id,
                json_module.dumps(result.model_dump()),
                ttl_minutes=1440,
                scope="summarize",
            )
        except (TypeError, ValueError) as e:
            logger.warning("Failed to cache summary: %s", e)

        logger.info("Summary: %d chars (from %d)", result.summary_length, result.original_length)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Summarize error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Summarization failed due to an internal error."
        ) from e

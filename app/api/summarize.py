import hashlib
import json as json_module
import logging
from fastapi import APIRouter, HTTPException
from app.models.request_models import SummarizeRequest
from app.models.response_models import SummarizeResponse
from app.utils.cache import cache
from groq import Groq
import os
from app.core.config import SUMMARY_CACHE_PREFIX
from app.prompts.summarize_prompt import SUMMARIZE_PROMPT

logger = logging.getLogger(__name__)

router = APIRouter()

llm = Groq(api_key=os.environ.get("GROQ_API_KEY"))

@router.post("/summarize", response_model=SummarizeResponse)
async def summarize_post(request: SummarizeRequest):
    try:
        logger.info(f"Summarize request from {request.user_id}")

        content = request.post_content.strip()

        if len(content) < 30:
            return SummarizeResponse(
                summary=content,
                original_length=len(content),
                summary_length=len(content),
            )

        cache_key = f"{SUMMARY_CACHE_PREFIX}{hashlib.md5(content.encode()).hexdigest()}"
        cached = cache.get(cache_key, request.user_id)
        if cached:
            logger.info("⚡ Returning cached summary")
            data = json_module.loads(cached)
            return SummarizeResponse(**data)

        llm_response = llm.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": SUMMARIZE_PROMPT.format(content=content)},
                {"role": "user",   "content": "Summarize this post concisely"},
            ],
            temperature=0.3,
            max_tokens=150,
        )

        summary = llm_response.choices[0].message.content.strip()
        result  = SummarizeResponse(
            summary=summary,
            original_length=len(content),
            summary_length=len(summary),
        )

        cache.set(cache_key, request.user_id, json_module.dumps(result.dict()), ttl_minutes=1440)

        logger.info(f" Summary: {result.summary_length} chars (from {result.original_length})")
        return result

    except Exception as e:
        logger.error(f"Summarize error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Summarization failed: {str(e)}")
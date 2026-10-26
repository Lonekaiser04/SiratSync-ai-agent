"""
Post-summarization endpoint for SiratSync Community.

Pipeline:
1. Input sanitization: Strips zero-width characters, collapses emoji and punctuation spam,
   and normalizes excessive whitespace.
2. Very short input preservation: Returns very short posts unchanged without LLM round-trip.
3. Language detection: Accurately identifies English, Urdu, Arabic, or Roman Urdu.
4. Structure budgeting: Exactly 2 bullet points for short posts, exactly 3 for long posts.
5. Cache lookup: Leverages Redis/in-memory cache across users for identical public posts.
6. Sacred text & sentence integrity: Preserves Quran, Hadith, duas, and complete sentences.
7. Model execution & fallback: Invokes primary model (openai/gpt-oss-120b) with transparent
   fallback to openai/gpt-oss-20b on retryable provider errors.
8. Output post-processing: Enforces bullet structure and terminal punctuation.
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

_MIN_CONTENT_LENGTH_FOR_SUMMARY = 35

_ZERO_WIDTH_CHARS = re.compile(r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad]")
_REPEATED_PUNCTUATION = re.compile(r"([!?.,;:~-])\1{2,}")
_REPEATED_SPACES = re.compile(r"[ \t]+")
_REPEATED_NEWLINES = re.compile(r"\n{3,}")
_PREAMBLE_PATTERN = re.compile(
    r"^(?:here is a summary(?: of the post)?\s*:?|summary(?: of the post)?\s*:|in summary\s*:|key takeaways\s*:)\s*",
    re.IGNORECASE,
)
_TERMINAL_PUNCTUATION = {".", "!", "?", "۔", "؟", '"', "'", "”", "’"}

_URDU_SPECIFIC_CHARS = set("ٹڈڑںےہئےپچژگ")
_URDU_WORDS = {
    "ہیں", "ہوں", "تھا", "تھی", "تھے", "کے", "کی", "کو", "میں", "نے", "سے",
    "اور", "کا", "کر", "ہے", "پر", "بھی", "آپ", "ان", "یہ", "وہ", "ہمارا", "تم",
}
_ROMAN_URDU_WORDS = {
    "hai", "hain", "ke", "ki", "ka", "ko", "se", "mein", "me", "aur", "ye", "yeh",
    "wo", "woh", "kya", "bhi", "nahi", "kare", "karna", "apne", "apni", "hoga",
    "hogi", "humein", "unko", "meri", "mera", "namaz", "roza", "dua", "allah",
    "bhai", "behn", "bohat", "kuch", "shukriya", "jazakallah", "deen", "subah", "shaam",
}


def detect_content_language(text: str) -> str:
    """Detects if content is Urdu, Arabic, Roman Urdu, or English."""
    arabic_script_chars = [c for c in text if "\u0600" <= c <= "\u06FF" or "\u0750" <= c <= "\u077F"]
    if len(arabic_script_chars) >= 4:
        if any(c in _URDU_SPECIFIC_CHARS for c in text):
            return "Urdu"
        words = set(text.split())
        if words.intersection(_URDU_WORDS):
            return "Urdu"
        return "Arabic"

    words_lower = set(re.findall(r"\b[a-z]+\b", text.lower()))
    roman_urdu_matches = words_lower.intersection(_ROMAN_URDU_WORDS)
    if len(roman_urdu_matches) >= 3 or (len(words_lower) <= 15 and len(roman_urdu_matches) >= 2):
        return "Roman Urdu"

    return "English"


def preprocess_post_content(raw_content: str) -> tuple[str, bool]:
    """
    Cleans noisy formatting, zero-width characters, and spam while preserving authentic multilingual content.
    Returns (cleaned_content, is_trivial_or_very_short).
    Very short posts (< 35 chars or symbol-only) are preserved unchanged.
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

    # Check if content has meaningful letters
    has_letters = any(c.isalnum() for c in cleaned)
    if not has_letters:
        return cleaned, True

    return cleaned, False


def _get_adaptive_max_tokens(is_short_or_length: bool | int) -> int:
    """Provides ample token allowance so neither English nor multilingual BPE tokens truncate mid-sentence."""
    if isinstance(is_short_or_length, bool):
        return 450 if is_short_or_length else 750
    if is_short_or_length <= 250:
        return 100
    if is_short_or_length <= 1000:
        return 250
    return 450


def clean_summary_output(raw_summary: str, original_content: str, target_bullets: int = 0) -> str:
    """
    Strips LLM meta-preambles, formats clean bullet points, ensures complete sentences,
    removes dangling truncated clauses, and supports multilingual terminal punctuation.
    """
    summary = raw_summary.strip()
    summary = _PREAMBLE_PATTERN.sub("", summary).strip()

    if not summary:
        cutoff = original_content[:200].rfind(" ")
        return original_content[: cutoff if cutoff > 50 else 200].strip()

    lines = [line.strip() for line in summary.split("\n") if line.strip()]
    has_bullet_markers = any(re.match(r"^(?:[•\-\*]|\d+[\.\)])\s*", line) for line in lines)

    # If single unbulleted text that was abruptly truncated mid-sentence
    if not has_bullet_markers and target_bullets == 0 and len(lines) == 1:
        single = lines[0]
        if len(single) > 50 and single[-1] not in _TERMINAL_PUNCTUATION:
            last_punct = max(
                single.rfind("."),
                single.rfind("!"),
                single.rfind("?"),
                single.rfind("۔"),
                single.rfind("؟"),
            )
            if last_punct > len(single) * 0.5:
                single = single[: last_punct + 1].strip()
        if single[-1] not in _TERMINAL_PUNCTUATION:
            single += "۔" if any("\u0600" <= c <= "\u06FF" for c in single) else "."
        return single

    cleaned_bullets: list[str] = []
    for line in lines:
        m = re.match(r"^(?:[•\-\*]|\d+[\.\)])\s*(.*)", line)
        bullet_text = m.group(1).strip() if m else line

        if not bullet_text:
            continue

        # If bullet was cut off mid-sentence
        if len(bullet_text) > 40 and bullet_text[-1] not in _TERMINAL_PUNCTUATION:
            last_punct = max(
                bullet_text.rfind("."),
                bullet_text.rfind("!"),
                bullet_text.rfind("?"),
                bullet_text.rfind("۔"),
                bullet_text.rfind("؟"),
            )
            if last_punct > len(bullet_text) * 0.6:
                bullet_text = bullet_text[: last_punct + 1].strip()

        if bullet_text[-1] not in _TERMINAL_PUNCTUATION:
            if any("\u0600" <= c <= "\u06FF" for c in bullet_text):
                bullet_text += "۔"
            else:
                bullet_text += "."

        should_prefix_bullet = has_bullet_markers or len(lines) > 1
        cleaned_bullets.append(f"• {bullet_text}" if should_prefix_bullet else bullet_text)

    if target_bullets > 0 and len(cleaned_bullets) > target_bullets:
        cleaned_bullets = cleaned_bullets[:target_bullets]

    if cleaned_bullets:
        return "\n".join(cleaned_bullets)

    if summary[-1] not in _TERMINAL_PUNCTUATION:
        summary += "۔" if any("\u0600" <= c <= "\u06FF" for c in summary) else "."

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
        cleaned_content, is_trivial_or_very_short = preprocess_post_content(raw_content)

        # Very short posts: keep unchanged
        if is_trivial_or_very_short:
            logger.info("request_id=%s Very short or trivial content — keeping unchanged", request_id)
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
        lang = detect_content_language(safe_content)
        word_count = len(safe_content.split())
        is_short = word_count <= 120 or len(safe_content) <= 650

        if is_short:
            target_bullets = 2
            format_instruction = (
                f"Generate EXACTLY 2 bullet points in {lang}. Each must be a complete, grammatically sound sentence "
                "capturing the core message and key facts."
            )
        else:
            target_bullets = 3
            format_instruction = (
                f"Generate EXACTLY 3 concise bullet points in {lang}. Each must be a complete, grammatically sound sentence "
                "capturing the main context, key facts, and conclusion."
            )

        max_tokens = _get_adaptive_max_tokens(is_short)

        try:
            llm_result = await llm_service.generate_completion(
                messages=[
                    {
                        "role": "system",
                        "content": SUMMARIZE_PROMPT.format(
                            content=safe_content,
                            format_instruction=format_instruction,
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Summarize this {lang} post faithfully into {'2' if is_short else '3'} bullet points in {lang}.",
                    },
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

        final_summary = clean_summary_output(llm_result.content, safe_content, target_bullets=target_bullets)

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
            "request_id=%s Summary produced: %d chars (from %d) [lang=%s, target_bullets=%d, model=%s, fallback=%s]",
            request_id,
            result.summary_length,
            result.original_length,
            lang,
            target_bullets,
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

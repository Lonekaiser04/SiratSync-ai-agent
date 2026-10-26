"""
Post-summarization endpoint for SiratSync Community.

Core Requirements:
1. English-Only Summarization:
   - Summarize English text ONLY in English.
   - Preserve Urdu, Kashmiri, Arabic, and other non-English content completely unchanged.
   - If no English content exists in the post, return the original post unchanged.
2. Length Budgeting:
   - Very short posts (< 35 chars or < 6 words) remain unchanged.
   - Short posts (<= 80 words and <= 500 chars) get exactly 2 concise bullets in English.
   - Long posts (> 80 words or > 500 chars) get exactly 3 concise bullets in English.
3. Sacred Text Integrity:
   - Never modify, translate, paraphrase, or truncate Quranic verses, Hadith, duas, or quoted Arabic text.
4. Mixed-Language Structure:
   - Summarize only the English portion into 2 or 3 bullets in English.
   - Preserve all non-English text (Arabic verses, Hadith, duas, Urdu, Kashmiri) word-for-word, unaltered.
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
_TERMINAL_PUNCTUATION = {".", "!", "?", '"', "'", "”", "’"}

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
    "karo", "raha", "rahi", "rahe", "tha", "thi", "the", "par", "pe", "sab", "hum",
    "bare", "baat", "karenge", "musalman", "zaroori", "zaroor", "liye", "har", "acha",
    "achi", "kisi", "aik", "ek", "sirf", "batao", "bataiye", "shuru", "khatam", "dost",
}

_ENGLISH_COMMON_WORDS = {
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "i", "it", "for", "not",
    "on", "with", "he", "as", "you", "do", "at", "this", "but", "his", "by", "from",
    "they", "we", "say", "her", "she", "or", "an", "will", "my", "one", "all", "would",
    "there", "their", "what", "so", "up", "out", "if", "about", "who", "get", "which",
    "go", "me", "when", "make", "can", "like", "time", "no", "just", "him", "know",
    "take", "people", "into", "year", "your", "good", "some", "could", "them", "see",
    "other", "than", "then", "now", "look", "only", "come", "its", "over", "think",
    "also", "back", "after", "use", "two", "how", "our", "work", "first", "well", "way",
    "even", "new", "want", "because", "any", "these", "give", "day", "most", "us",
    "life", "community", "prayer", "prophet", "patience", "guidance", "peace", "islamic",
    "muslim", "faith", "worship", "fasting", "daily", "quran", "hadith", "reflection",
    "transformation", "hardship", "blessing", "charity", "believers", "sincere", "action",
    "actions", "transforms", "importance", "remember", "difficulties", "spiritual",
}


def extract_arabic_sacred_segments(text: str) -> list[str]:
    """
    Extracts contiguous Arabic text segments (Quranic verses, Hadith, duas, or Arabic phrases)
    from content while ignoring pure Urdu commentary words.
    """
    if not text:
        return []
    pattern = re.compile(
        r"[\u0600-\u064A\u064B-\u065F\u0670-\u06D3\u06D5-\u06ED\uFD3E\uFD3F\uFDF2\uFDFD]+"
        r"(?:\s+[\u0600-\u064A\u064B-\u065F\u0670-\u06D3\u06D5-\u06ED\uFD3E\uFD3F\uFDF2\uFDFD]+)*"
    )
    segments: list[str] = []
    for match in pattern.finditer(text):
        chunk = match.group(0).strip()
        if len(chunk) < 6:
            continue
        if any(c in _URDU_SPECIFIC_CHARS for c in chunk):
            continue
        words = chunk.split()
        if len(words) >= 2 and set(words).issubset(_URDU_WORDS):
            continue
        segments.append(chunk)
    return segments


def extract_non_english_segments(text: str) -> list[str]:
    """
    Extracts contiguous non-English text segments (Arabic script, Urdu, Kashmiri, etc.)
    including sacred text, verses, Hadiths, duas, or non-English sentences.
    """
    if not text:
        return []
    pattern = re.compile(
        r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]+"
        r"(?:[\s\d:()\-.,/–—]+[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]+)*"
    )
    segments: list[str] = []
    for match in pattern.finditer(text):
        chunk = match.group(0).strip()
        if len(chunk) >= 6:
            segments.append(chunk)
    return segments


def extract_english_words(text: str) -> list[str]:
    """
    Extracts meaningful English words, filtering out Roman Urdu indicator words.
    """
    latin_tokens = re.findall(r"\b[a-zA-Z]{2,}\b", text)
    return [t for t in latin_tokens if t.lower() not in _ROMAN_URDU_WORDS]


def has_english_content(text: str) -> bool:
    """
    Determines whether the post contains meaningful English content to summarize.
    Returns False for pure Urdu, Arabic, Kashmiri, Roman Urdu, or non-English text.
    """
    english_words = extract_english_words(text)
    if len(english_words) < 4:
        return False

    # Check for presence of recognized English words
    recognized_count = sum(1 for w in english_words if w.lower() in _ENGLISH_COMMON_WORDS)
    if recognized_count >= 2:
        return True

    # Check if ratio of distinct English-like words is high
    return len(english_words) >= 5


def detect_content_language(text: str) -> str:
    """Legacy helper for testing language classification."""
    arabic_chars = [c for c in text if "\u0600" <= c <= "\u06FF" or "\u0750" <= c <= "\u077F"]
    latin_words = re.findall(r"\b[a-zA-Z]{3,}\b", text)
    has_urdu_chars = any(c in _URDU_SPECIFIC_CHARS for c in text)
    urdu_words = [w for w in text.split() if w in _URDU_WORDS]

    if has_english_content(text):
        return "English"

    words_lower = set(re.findall(r"\b[a-z]+\b", text.lower()))
    roman_urdu_matches = words_lower.intersection(_ROMAN_URDU_WORDS)
    if len(roman_urdu_matches) >= 3:
        return "Roman Urdu"

    if (has_urdu_chars or len(urdu_words) >= 1) and len(arabic_chars) >= 4:
        return "Urdu"

    if len(arabic_chars) >= 6:
        return "Arabic"

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

    has_letters = any(c.isalnum() for c in cleaned)
    if not has_letters:
        return cleaned, True

    return cleaned, False


def _get_adaptive_max_tokens(is_short_or_length: bool | int) -> int:
    """Provides ample token allowance for English summaries without mid-sentence truncation."""
    if isinstance(is_short_or_length, bool):
        return 450 if is_short_or_length else 750
    if is_short_or_length <= 250:
        return 100
    if is_short_or_length <= 1000:
        return 250
    return 450


def clean_summary_output(
    raw_summary: str,
    original_content: str,
    target_bullets: int = 0,
    preserved_segments: list[str] | None = None,
) -> str:
    """
    Strips LLM meta-preambles, formats clean English bullet points, ensures complete sentences,
    removes dangling truncated clauses, and preserves non-English & sacred segments verbatim.
    """
    summary = raw_summary.strip()
    summary = _PREAMBLE_PATTERN.sub("", summary).strip()

    if not summary:
        cutoff = original_content[:200].rfind(" ")
        return original_content[: cutoff if cutoff > 50 else 200].strip()

    lines = [line.strip() for line in summary.split("\n") if line.strip()]
    has_bullet_markers = any(re.match(r"^(?:[•\-\*]|\d+[\.\)])\s*", line) for line in lines)

    # If single unbulleted text that was cut off mid-sentence
    if not has_bullet_markers and target_bullets == 0 and len(lines) == 1:
        single = lines[0]
        if len(single) > 50 and single[-1] not in _TERMINAL_PUNCTUATION:
            last_punct = max(single.rfind("."), single.rfind("!"), single.rfind("?"))
            if last_punct > len(single) * 0.5:
                single = single[: last_punct + 1].strip()
        if single[-1] not in _TERMINAL_PUNCTUATION:
            single += "."
        return single

    cleaned_bullets: list[str] = []
    for line in lines:
        # If line contains preserved non-English segment, leave it as is
        if preserved_segments and any(seg in line for seg in preserved_segments if len(seg) >= 8):
            cleaned_bullets.append(line)
            continue

        m = re.match(r"^(?:[•\-\*]|\d+[\.\)])\s*(.*)", line)
        bullet_text = m.group(1).strip() if m else line

        if not bullet_text:
            continue

        # If bullet was cut off mid-sentence
        if len(bullet_text) > 40 and bullet_text[-1] not in _TERMINAL_PUNCTUATION:
            last_punct = max(bullet_text.rfind("."), bullet_text.rfind("!"), bullet_text.rfind("?"))
            if last_punct > len(bullet_text) * 0.6:
                bullet_text = bullet_text[: last_punct + 1].strip()

        if bullet_text[-1] not in _TERMINAL_PUNCTUATION:
            bullet_text += "۔" if any("\u0600" <= c <= "\u06FF" for c in bullet_text) else "."

        should_prefix_bullet = has_bullet_markers or len(lines) > 1
        cleaned_bullets.append(f"• {bullet_text}" if should_prefix_bullet else bullet_text)

    # Separate bullets from preserved non-English segments for counting
    actual_bullets = [b for b in cleaned_bullets if b.startswith("• ")]
    other_lines = [b for b in cleaned_bullets if not b.startswith("• ")]

    if target_bullets > 0 and len(actual_bullets) > target_bullets:
        actual_bullets = actual_bullets[:target_bullets]

    final_text = "\n".join(actual_bullets + other_lines) if (actual_bullets or other_lines) else summary

    # Ensure preserved sacred Arabic and non-English segments are completely retained
    if preserved_segments:
        missing_segments = [
            seg for seg in preserved_segments
            if len(seg) >= 8 and seg not in final_text
        ]
        if missing_segments:
            non_eng_block = "\n\n".join(missing_segments)
            final_text = f"{final_text}\n\n{non_eng_block}"

    return final_text


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

        # 1. Very short posts (< 35 chars): remain unchanged
        if is_trivial_or_very_short:
            logger.info("request_id=%s Very short or trivial content — keeping unchanged", request_id)
            return SummarizeResponse(
                summary=cleaned_content,
                original_length=len(raw_content),
                summary_length=len(cleaned_content),
            )

        safe_content = sanitize_user_text(cleaned_content, max_length=settings.MAX_POST_CONTENT_LENGTH)

        # 2. English-Only Rule: If no English content exists, return original post unchanged!
        # "Summarize English text only. Preserve Urdu, Kashmiri, Arabic, and other non-English content unchanged."
        # "If no English content exists, return the original post unchanged."
        if not has_english_content(safe_content):
            logger.info(
                "request_id=%s No English content detected (pure Urdu, Arabic, Kashmiri, or non-English) — keeping unchanged",
                request_id,
            )
            return SummarizeResponse(
                summary=cleaned_content,
                original_length=len(raw_content),
                summary_length=len(cleaned_content),
            )

        english_words = extract_english_words(safe_content)
        english_word_count = len(english_words)

        # If English word count is very short (< 6 words), keep unchanged
        if english_word_count < 6:
            logger.info("request_id=%s Very short English content (< 6 words) — keeping unchanged", request_id)
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

        # 3. Detect non-English content to preserve (Quran, Hadith, duas, Arabic text, Urdu, Kashmiri)
        non_english_segments = extract_non_english_segments(safe_content)
        is_mixed = len(non_english_segments) > 0

        # 4. Length Budgeting: short posts get 2 concise bullets, long posts get 3
        is_short = english_word_count <= 80 and len(safe_content) <= 500
        target_bullets = 2 if is_short else 3

        if is_mixed:
            format_instruction = (
                f"STRICT RULE: Summarize ONLY the English text into EXACTLY {target_bullets} concise bullet points in English.\n"
                f"Preserve all non-English text, Arabic verses, Hadith, duas, and quotes EXACTLY as provided in the post, word-for-word, unaltered.\n"
                f"Do NOT summarize, translate, paraphrase, or truncate the non-English or Arabic text. Include the exact unaltered text alongside your English summary bullet points."
            )
        elif is_short:
            format_instruction = (
                "Generate EXACTLY 2 concise bullet points in English. Each must be a complete, grammatically sound sentence "
                "capturing the core message and key facts."
            )
        else:
            format_instruction = (
                "Generate EXACTLY 3 concise bullet points in English. Each must be a complete, grammatically sound sentence "
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
                        "content": (
                            f"Summarize only the English portion into {target_bullets} concise bullet points in English. "
                            f"{'Preserve all non-English and Arabic text verbatim and unchanged.' if is_mixed else ''}"
                        ),
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

        final_summary = clean_summary_output(
            llm_result.content,
            safe_content,
            target_bullets=target_bullets,
            preserved_segments=non_english_segments if is_mixed else None,
        )

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
            "request_id=%s English summary produced: %d chars (from %d) [is_mixed=%s, target_bullets=%d, model=%s, fallback=%s]",
            request_id,
            result.summary_length,
            result.original_length,
            is_mixed,
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

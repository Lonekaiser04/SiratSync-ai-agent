"""
Post-summarization endpoint for SiratSync Community.

Core Requirements:
1. Universal Multilingual Summarization:
   - Accurately summarize posts of any supported language (English, Urdu, Kashmiri, Roman Urdu, Arabic, Hindi, etc.) and content type.
   - Preserve original meaning, key points, factual claims, and context.
2. Absolute Arabic Text Integrity:
   - NEVER translate, rewrite, modify, or omit Arabic text.
   - Preserve Arabic wording exactly as it appears in the original post and return it unchanged in the summary.
   - Quranic verses, Hadith, duas, and Arabic quotes remain 100% unaltered.
3. Length Budgeting:
   - Very short posts (< 35 chars or < 6 words) remain unchanged.
   - Short posts (<= 80 words and <= 500 chars) get exactly 2 concise bullets.
   - Long posts (> 80 words or > 500 chars) get exactly 3 concise bullets.
4. Robust Bullet Formatting:
   - Each bullet starts with "• ".
   - Sentences are complete and end with proper terminal punctuation based on script:
     * Urdu / Kashmiri: '۔'
     * English / Roman Urdu: '.'
     * Hindi: '।'
     * Arabic: '.' or verse punctuation
5. Zero Hallucination & Clean Output:
   - No conversational preambles or filler.
   - Graceful error handling and multi-model fallback.
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
    r"^(?:here is a summary(?: of the post)?\s*:?|summary(?: of the post)?\s*:|in summary\s*:|key takeaways\s*:|خلاصہ\s*:|ملخص\s*:)\s*",
    re.IGNORECASE,
)
_TERMINAL_PUNCTUATION = {".", "!", "?", '"', "'", "”", "’", "۔", "؟", "।", "۝"}

_URDU_SPECIFIC_CHARS = set("ٹڈڑںےہئےپچژگ")
_KASHMIRI_SPECIFIC_CHARS = set("ؠۄۆێۍ؋")
_KASHMIRI_WORDS = {
    "چھُ", "چھِ", "مَنٛز", "تَہ", "تہٕ", "أکِس", "سٲری", "پانہٕ", "کٔرِو", "روزِو", "یِم", "تِم",
}
_URDU_WORDS = {
    "ہیں", "ہوں", "تھا", "تھی", "تھے", "کے", "کی", "کو", "میں", "نے", "سے",
    "اور", "کا", "کر", "ہے", "پر", "بھی", "آپ", "ان", "یہ", "وہ", "ہمارا", "تم",
    "کیا", "نہیں", "کرنا", "کریں", "بات", "بہت", "سب", "ہم", "والے", "تک",
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
    from content while ignoring pure Urdu/Kashmiri commentary words.
    """
    if not text:
        return []
    pattern = re.compile(
        r"[\u0600-\u064A\u064B-\u065F\u0670-\u06D3\u06D5-\u06ED\uFD3E\uFD3F\uFDF2\uFDFD]+"
        r"(?:[\s\d:()\-.,/–—«»\"\'\[\]]+[\u0600-\u064A\u064B-\u065F\u0670-\u06D3\u06D5-\u06ED\uFD3E\uFD3F\uFDF2\uFDFD]+)*"
    )
    segments: list[str] = []
    for match in pattern.finditer(text):
        chunk = match.group(0).strip(" ,.-:;()[]\"'«»")
        if len(chunk) < 6:
            continue
        if any(c in _URDU_SPECIFIC_CHARS for c in chunk):
            continue
        if any(c in _KASHMIRI_SPECIFIC_CHARS for c in chunk):
            continue
        words = chunk.split()
        if len(words) >= 2 and set(words).issubset(_URDU_WORDS):
            continue
        if len(words) >= 2 and set(words).issubset(_KASHMIRI_WORDS):
            continue
        segments.append(chunk)
    return segments


def extract_non_english_segments(text: str) -> list[str]:
    """
    Extracts contiguous non-English text segments (Arabic, Urdu, Kashmiri, etc.).
    """
    if not text:
        return []
    pattern = re.compile(
        r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]+"
        r"(?:[\s\d:()\-.,/–—«»\"\'\[\]]+[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]+)*"
    )
    segments: list[str] = []
    for match in pattern.finditer(text):
        chunk = match.group(0).strip(" ,.-:;()[]\"'«»")
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
    Determines whether the post contains meaningful English content.
    """
    english_words = extract_english_words(text)
    if len(english_words) < 4:
        return False
    recognized_count = sum(1 for w in english_words if w.lower() in _ENGLISH_COMMON_WORDS)
    if recognized_count >= 2:
        return True
    return len(english_words) >= 5


def detect_content_language(text: str) -> str:
    """
    Detects the primary language of the post content:
    'English', 'Urdu', 'Kashmiri', 'Roman Urdu', 'Arabic', 'Hindi', etc.
    Correctly recognizes surrounding language even when Arabic verses/Hadiths are quoted.
    """
    if not text or not text.strip():
        return "English"

    # Hindi (Devanagari script)
    hindi_chars = re.findall(r"[\u0900-\u097F]", text)
    if len(hindi_chars) >= 10:
        return "Hindi"

    # Kashmiri specific characters or distinct Kashmiri vocabulary
    kashmiri_chars = [c for c in text if c in _KASHMIRI_SPECIFIC_CHARS]
    kashmiri_words = [w for w in text.split() if w in _KASHMIRI_WORDS]
    if len(kashmiri_chars) >= 2 or len(kashmiri_words) >= 2:
        return "Kashmiri"

    has_urdu_chars = any(c in _URDU_SPECIFIC_CHARS for c in text)
    urdu_words = [w for w in text.split() if w in _URDU_WORDS]
    arabic_chars = [c for c in text if "\u0600" <= c <= "\u06FF" or "\u0750" <= c <= "\u077F"]

    latin_tokens = re.findall(r"\b[a-zA-Z]{2,}\b", text)
    latin_words_lower = [w.lower() for w in latin_tokens]

    english_word_count = sum(1 for w in latin_words_lower if w in _ENGLISH_COMMON_WORDS)
    roman_urdu_count = sum(1 for w in latin_words_lower if w in _ROMAN_URDU_WORDS)

    # Predominantly Latin script
    if len(latin_tokens) >= 4:
        if roman_urdu_count >= 3 and roman_urdu_count >= english_word_count:
            return "Roman Urdu"
        if english_word_count >= 2 or len(latin_tokens) > len(arabic_chars):
            return "English"

    # Arabic script check
    if len(arabic_chars) >= 4:
        if has_urdu_chars or len(urdu_words) >= 2:
            return "Urdu"
        if not has_urdu_chars and len(urdu_words) == 0:
            return "Arabic"
        if len(urdu_words) >= 1:
            return "Urdu"
        return "Arabic"

    # Short Latin texts
    if len(latin_tokens) >= 2:
        if roman_urdu_count > english_word_count:
            return "Roman Urdu"
        return "English"

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
    """Provides ample token allowance for summaries without mid-sentence truncation."""
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
    language: str = "English",
) -> str:
    """
    Strips LLM meta-preambles, formats clean bullet points, ensures complete sentences,
    removes dangling truncated clauses, and guarantees Arabic text is preserved word-for-word,
    never translated, modified, or omitted.
    """
    summary = raw_summary.strip()
    summary = _PREAMBLE_PATTERN.sub("", summary).strip()

    if not summary:
        cutoff = original_content[:200].rfind(" ")
        return original_content[: cutoff if cutoff > 50 else 200].strip()

    # Prevent accidental translation of pure Arabic posts into English
    if language == "Arabic":
        latin_words = re.findall(r"\b[a-zA-Z]{3,}\b", summary)
        if len(latin_words) >= 4:
            logger.warning("Arabic post was translated into English by LLM. Reverting to original Arabic text.")
            return original_content

    lines = [line.strip() for line in summary.split("\n") if line.strip()]
    has_bullet_markers = any(re.match(r"^(?:[•\-\*]|\d+[\.\)])\s*", line) for line in lines)

    # If single unbulleted text that was cut off mid-sentence
    if not has_bullet_markers and target_bullets == 0 and len(lines) == 1:
        single = lines[0]
        if len(single) > 50 and single[-1] not in _TERMINAL_PUNCTUATION:
            last_punct = max(single.rfind("."), single.rfind("!"), single.rfind("?"), single.rfind("۔"))
            if last_punct > len(single) * 0.5:
                single = single[: last_punct + 1].strip()
        if single[-1] not in _TERMINAL_PUNCTUATION:
            single += "۔" if language in ("Urdu", "Kashmiri") else "."
        return single

    cleaned_bullets: list[str] = []
    for line in lines:
        # If line contains an exact preserved segment, preserve it as is without bullet prefixing
        if preserved_segments and any(seg in line for seg in preserved_segments if len(seg) >= 8):
            cleaned_bullets.append(line)
            continue

        m = re.match(r"^(?:[•\-\*]|\d+[\.\)])\s*(.*)", line)
        if m:
            bullet_text = m.group(1).strip()
            is_bullet = True
        elif not has_bullet_markers and len(lines) > 1:
            bullet_text = line
            is_bullet = True
        else:
            bullet_text = line
            is_bullet = False

        if not bullet_text:
            continue

        # If bullet was cut off mid-sentence
        if len(bullet_text) > 40 and bullet_text[-1] not in _TERMINAL_PUNCTUATION:
            last_punct = max(
                bullet_text.rfind("."),
                bullet_text.rfind("!"),
                bullet_text.rfind("?"),
                bullet_text.rfind("۔"),
            )
            if last_punct > len(bullet_text) * 0.6:
                bullet_text = bullet_text[: last_punct + 1].strip()

        if bullet_text[-1] not in _TERMINAL_PUNCTUATION:
            if language in ("Urdu", "Kashmiri"):
                bullet_text += "۔"
            elif language == "Hindi":
                bullet_text += "।"
            elif language == "Arabic":
                bullet_text += "."
            else:
                bullet_text += "۔" if any("\u0600" <= c <= "\u06FF" for c in bullet_text) else "."

        cleaned_bullets.append(f"• {bullet_text}" if is_bullet else bullet_text)

    # Separate bullets from preserved text lines for counting
    actual_bullets = [b for b in cleaned_bullets if b.startswith("• ")]
    other_lines = [b for b in cleaned_bullets if not b.startswith("• ")]

    if target_bullets > 0 and len(actual_bullets) > target_bullets:
        actual_bullets = actual_bullets[:target_bullets]

    final_text = "\n".join(actual_bullets + other_lines) if (actual_bullets or other_lines) else summary

    # CRITICAL: Ensure preserved Arabic text from original post is never omitted!
    if preserved_segments:
        missing_segments = [
            seg for seg in preserved_segments
            if len(seg) >= 8 and seg not in final_text
        ]
        if missing_segments:
            arabic_block = "\n\n".join(missing_segments)
            final_text = f"{final_text}\n\n{arabic_block}" if final_text else arabic_block

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

        # 1. Very short posts (< 35 chars or trivial noise): keep unchanged
        if is_trivial_or_very_short:
            logger.info("request_id=%s Very short or trivial content — keeping unchanged", request_id)
            return SummarizeResponse(
                summary=cleaned_content,
                original_length=len(raw_content),
                summary_length=len(cleaned_content),
            )

        safe_content = sanitize_user_text(cleaned_content, max_length=settings.MAX_POST_CONTENT_LENGTH)

        # Word count calculation supporting any script (Urdu, Arabic, Kashmiri, English, etc.)
        all_words = re.findall(r"\S+", safe_content)
        total_word_count = len(all_words)

        # If total word count is very short (< 6 words), keep unchanged
        if total_word_count < 6:
            logger.info("request_id=%s Very short content (< 6 words) — keeping unchanged", request_id)
            return SummarizeResponse(
                summary=cleaned_content,
                original_length=len(raw_content),
                summary_length=len(cleaned_content),
            )

        # Check response cache (shared cross-user for identical posts)
        cached = await cache.get(cleaned_content, request.user_id, scope="summarize")
        if cached:
            try:
                data = json_module.loads(cached)
                logger.info("request_id=%s Summarize cache hit", request_id)
                return SummarizeResponse(**data)
            except (json_module.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning("request_id=%s Corrupt summarize cache entry, regenerating: %s", request_id, e)

        # 2. Multilingual Language Detection
        detected_language = detect_content_language(safe_content)

        # 3. Detect Arabic & non-English content to preserve
        arabic_segments = extract_arabic_sacred_segments(safe_content)
        other_segments = []
        if detected_language == "English":
            urdu_kashmiri_pattern = re.compile(
                r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]+"
                r"(?:[\s\d:()\-.,/–—«»\"\'\[\]]+[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]+)*"
            )
            for m in urdu_kashmiri_pattern.finditer(safe_content):
                chunk = m.group(0).strip(" ,.-:;()[]\"'«»")
                if len(chunk) >= 6:
                    other_segments.append(chunk)

        all_preserved_segments = list(dict.fromkeys(arabic_segments + other_segments))
        has_preserved = len(all_preserved_segments) > 0
        is_mixed = has_preserved and detected_language != "Arabic"

        # 4. Length Budgeting: short posts get 2 concise bullets, long posts get 3
        is_short = total_word_count <= 80 and len(safe_content) <= 500
        target_bullets = 2 if is_short else 3

        # 5. Tailored format instructions per language and content type
        if detected_language == "Urdu":
            format_instruction = (
                f"Generate EXACTLY {target_bullets} concise bullet points in URDU script (اردو). "
                f"Each bullet point MUST be a complete, grammatically sound sentence ending with '۔'. "
                f"MANDATE: NEVER translate, rewrite, or alter any Arabic Quranic verses, Hadith, or duas. "
                f"Keep all Arabic wording exactly as it appears in the original post and return it unchanged."
            )
        elif detected_language == "Kashmiri":
            format_instruction = (
                f"Generate EXACTLY {target_bullets} concise bullet points in KASHMIRI script. "
                f"Each bullet point MUST be a complete sentence ending with '۔'. "
                f"MANDATE: NEVER translate, rewrite, or alter any Arabic Quranic verses, Hadith, or duas. "
                f"Keep all Arabic wording exactly as it appears in the original post and return it unchanged."
            )
        elif detected_language == "Roman Urdu":
            format_instruction = (
                f"Generate EXACTLY {target_bullets} concise bullet points in ROMAN URDU (Urdu in English/Latin alphabet). "
                f"Each bullet point MUST be a complete sentence ending with '.'. "
                f"MANDATE: NEVER translate, rewrite, or alter any Arabic Quranic verses, Hadith, or duas. "
                f"Keep all Arabic wording exactly as it appears in the original post and return it unchanged."
            )
        elif detected_language == "Arabic":
            format_instruction = (
                f"Generate a concise summary of EXACTLY {target_bullets} bullet points directly in ARABIC. "
                f"CRITICAL MANDATE: NEVER translate the Arabic text into English, Urdu, or any other language. "
                f"Preserve all Arabic Quranic verses, Hadith, duas, and Arabic wording EXACTLY as they appear in the original post."
            )
        elif detected_language == "Hindi":
            format_instruction = (
                f"Generate EXACTLY {target_bullets} concise bullet points in HINDI (हिन्दी). "
                f"Each bullet point MUST be a complete sentence ending with '।'. "
                f"MANDATE: NEVER translate, rewrite, or alter any Arabic Quranic verses, Hadith, or duas."
            )
        else:
            # English (default)
            if is_mixed:
                format_instruction = (
                    f"Generate EXACTLY {target_bullets} concise bullet points in English summarizing the key message.\n"
                    f"CRITICAL MANDATE: NEVER translate, rewrite, modify, or omit Arabic text. "
                    f"Preserve all Arabic Quranic verses, Hadith, duas, and quotes EXACTLY as provided in the post, "
                    f"word-for-word, unaltered alongside the English summary bullet points."
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

        user_prompt = (
            f"Summarize this post into {target_bullets} concise bullet points in {detected_language}. "
            f"MANDATE: Never translate, rewrite, modify, or omit Arabic text; preserve all Arabic wording exactly "
            f"as it appears in the original post and return it unchanged."
        )

        try:
            llm_result = await llm_service.generate_completion(
                messages=[
                    {
                        "role": "system",
                        "content": SUMMARIZE_PROMPT.format(
                            language=detected_language,
                            content=safe_content,
                            format_instruction=format_instruction,
                        ),
                    },
                    {
                        "role": "user",
                        "content": user_prompt,
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
            preserved_segments=all_preserved_segments if has_preserved else None,
            language=detected_language,
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
            "request_id=%s Summary produced: %d chars (from %d) [lang=%s, is_mixed=%s, target_bullets=%d, model=%s, fallback=%s]",
            request_id,
            result.summary_length,
            result.original_length,
            detected_language,
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

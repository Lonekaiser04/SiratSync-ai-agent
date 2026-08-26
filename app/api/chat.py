"""
Primary chat endpoint.

Pipeline: cache check -> memory write -> intent detection -> RAG retrieval
-> quick-reply short-circuit OR LLM generation -> action suggestions ->
response assembly + caching.
"""
from __future__ import annotations

import json as json_module
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Request
from groq import AsyncGroq, GroqError

from app.core.config import settings
from app.core.security import detect_prompt_injection, sanitize_user_text
from app.models.request_models import ChatRequest
from app.models.response_models import ActionsPayload, ChatResponse
from app.prompts.system_prompt import SYSTEM_PROMPT
from app.services.intent_service import intent_detector
from app.services.memory_service import memory
from app.services.rag_service import rag_service
from app.utils.cache import cache
from app.utils.helpers import get_quick_response

logger = logging.getLogger(__name__)

router = APIRouter()

llm = AsyncGroq(api_key=settings.GROQ_API_KEY)

_CONFIRM_WORDS = frozenset(
    {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "alright", "yes please"}
)

_VERSE_OR_SURAH_PATTERNS = [
    re.compile(r"(?:surah|surat|chapter)\s+[\w\s\-]+\s+(?:verse|ayat|ayah)\s+\d+", re.I),
    re.compile(r"\b([1-9]|[1-9]\d|1[01]\d|114):([1-9]\d{0,2})\b"),
    re.compile(r"(?:surah|surat)\s+\d{1,3}\b", re.I),
    re.compile(r"^(?:surah|surat)\s+[a-z\s\-]+$", re.I),
]


def _is_verse_or_surah_query(message_lower: str) -> bool:
    """Returns True if the message is asking for a specific verse or surah — RAG must handle it."""
    stripped = message_lower.strip()
    for i, pattern in enumerate(_VERSE_OR_SURAH_PATTERNS):
        target = stripped if i == len(_VERSE_OR_SURAH_PATTERNS) - 1 else message_lower
        if pattern.search(target):
            return True
    return False


def _fallback_actions() -> ActionsPayload:
    return ActionsPayload(
        reminders=[], habits=[], duas=[], resources=[], encouragement="", quick_actions=[]
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, http_request: Request):
    request_id = getattr(http_request.state, "request_id", "unknown")

    try:
        logger.info("request_id=%s Chat from user %s", request_id, request.user_id)

        cached_response = cache.get(request.message, request.user_id)
        if cached_response:
            logger.info("request_id=%s Cache hit — stats: %s", request_id, cache.stats)
            try:
                return ChatResponse(**json_module.loads(cached_response))
            except (json_module.JSONDecodeError, TypeError, ValueError) as e:
                # Corrupt cache entry shouldn't take down the request — log
                # and fall through to a fresh generation.
                logger.warning("request_id=%s Corrupt cache entry, regenerating: %s", request_id, e)

        memory.add_message(request.user_id, "user", request.message)

        server_context = memory.get_context(request.user_id, max_messages=6)
        conversation_context = request.context if request.context else server_context
        last_question = memory.get_last_question(request.user_id)

        if detect_prompt_injection(request.message) or (
            request.context and detect_prompt_injection(request.context)
        ):
            logger.warning(
                "request_id=%s Possible prompt injection pattern detected for user %s",
                request_id, request.user_id,
            )

        safe_message = sanitize_user_text(request.message, max_length=settings.MAX_MESSAGE_LENGTH)
        safe_context = (
            sanitize_user_text(conversation_context, max_length=settings.MAX_CONTEXT_LENGTH)
            if conversation_context
            else conversation_context
        )

        intent_result = intent_detector.detect(request.message)
        primary_intent = intent_result.primary_intent
        sub_intent = intent_result.sub_intent
        sentiment = intent_result.sentiment
        urgency = intent_result.urgency

        message_lower = request.message.lower().strip()

        if message_lower in _CONFIRM_WORDS:
            lq = (last_question or "").lower()
            cc = (conversation_context or "").lower()
            if "features" in lq or "learn more" in lq or "features" in cc:
                primary_intent = "app_features_inquiry"
            elif "salah" in lq or "prayer" in lq:
                primary_intent, sub_intent = "salah", "learn_more"
            elif "quran" in lq:
                primary_intent, sub_intent = "quran", "learn_more"

        logger.info(
            "request_id=%s Intent: %s | Sub: %s | Sentiment: %s",
            request_id, primary_intent, sub_intent, sentiment,
        )

        knowledge = rag_service.retrieve(request.message, top_k=5, user_id=request.user_id)

        user_profile = memory.get_user_profile(request.user_id)
        user_profile["urgency"] = urgency
        user_profile["sentiment"] = sentiment

        quick_reply = await get_quick_response(
            request.message,
            primary_intent,
            sub_intent,
            user_profile,
            context=conversation_context,
            last_question=last_question,
            user_id=request.user_id,
        )

        used_llm = False

        if quick_reply:
            reply = quick_reply
            logger.info("request_id=%s Quick response used", request_id)

        elif _is_verse_or_surah_query(message_lower):
            reply = rag_service.retrieve(request.message, top_k=5, user_id=request.user_id)
            logger.info("request_id=%s Verse/Surah RAG response used — LLM bypassed", request_id)

        elif rag_service._is_quran_topic_query(message_lower):
            reply = knowledge or rag_service.retrieve(
                request.message, top_k=5, user_id=request.user_id
            )
            logger.info("request_id=%s Quran topic RAG response used", request_id)

        else:
            prompt = SYSTEM_PROMPT.format(
                context=safe_context or "(No previous conversation)",
                user_profile=json_module.dumps(user_profile, indent=2),
                knowledge=knowledge or "(No specific knowledge retrieved)",
                question=safe_message,
            )

            temperature = 0.3 if primary_intent in ("technical", "factual") else 0.6
            max_tokens = 350 if urgency == "high" else 500

            try:
                llm_response = await llm.chat.completions.create(
                    model=settings.GROQ_MODEL,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": safe_message},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=settings.LLM_TIMEOUT_SECONDS,
                )
                reply = (llm_response.choices[0].message.content or "").strip()
                used_llm = True

                if not reply:
                    logger.warning("request_id=%s LLM returned empty content", request_id)
                    reply = (
                        "I wasn't able to form a complete answer to that. Could you "
                        "rephrase your question? 🤲"
                    )

            except GroqError as e:
                logger.error("request_id=%s Groq API error: %s", request_id, e, exc_info=True)
                reply = (
                    "I'm having trouble reaching my knowledge service right now. "
                    "Please try again shortly. JazakAllah khair for your patience. 🤲"
                )

            if len(reply) > 2000 and urgency != "high":
                cutoff = reply.rfind(".", 0, 2000)
                if cutoff == -1:
                    cutoff = 2000
                reply = reply[: cutoff + 1] + "\n\n_📲 Open the app for the full response._"

            logger.info("request_id=%s LLM reply generated (%d chars)", request_id, len(reply))

        from app.services.action_service import (
            get_motivational_quote,
            get_quick_reply_suggestions,
            suggest_actions,
        )

        actions = suggest_actions(
            primary_intent,
            user_profile,
            sub_intent=sub_intent,
            sentiment=sentiment,
            user_timezone=request.user_timezone,
        )
        suggestions = get_quick_reply_suggestions(primary_intent, sub_intent)

        motivational_quote = None
        if primary_intent == "struggling" or user_profile.get("consistency") == "struggling":
            motivational_quote = get_motivational_quote("struggling")
        elif primary_intent == "consistent" or user_profile.get("consistency") == "high":
            motivational_quote = get_motivational_quote("high")
        elif user_profile.get("consistency") == "medium":
            motivational_quote = get_motivational_quote("medium")

        memory.add_message(request.user_id, "assistant", reply)

        is_verse_query = _is_verse_or_surah_query(message_lower)
        is_quran_topic = rag_service._is_quran_topic_query(message_lower)
        used_rag = bool(knowledge and knowledge != "(No specific knowledge retrieved)")

        sources = _build_sources(
            reply=reply,
            is_verse_query=is_verse_query,
            is_quran_topic=is_quran_topic,
            used_rag=used_rag,
            was_quick_reply=bool(quick_reply),
        )

        response_data = {
            "reply": reply,
            "intent": primary_intent,
            "sub_intent": sub_intent,
            "sentiment": sentiment,
            "actions": actions,
            "suggestions": suggestions[:4],
            "motivational_quote": motivational_quote,
            "timestamp": datetime.now().isoformat(),
            "sources": sources,
        }

        try:
            cache.set(
                request.message,
                request.user_id,
                json_module.dumps(response_data),
                ttl_minutes=settings.RESPONSE_CACHE_TTL_MINUTES,
            )
        except (TypeError, ValueError) as e:
            # Non-JSON-serializable content shouldn't break the response.
            logger.warning("request_id=%s Failed to cache response: %s", request_id, e)

        return ChatResponse(**response_data)

    except Exception as e:
        logger.error("request_id=%s Chat error: %s", request_id, e, exc_info=True)
        return ChatResponse(
            reply=(
                "I'm having trouble processing your request right now. "
                "Please try again in a moment. JazakAllah khair for your patience. 🤲"
            ),
            intent="error",
            sub_intent=None,
            sentiment="neutral",
            actions=_fallback_actions(),
            suggestions=["Try again", "Browse Quran", "Check prayer times", "Contact support"],
            motivational_quote=None,
            timestamp=datetime.now().isoformat(),
        )


# ── Source definitions (single source of truth) ───────────────────────────
_SRC_ARABIC = {
    "type": "quran",
    "label": "القرآن الكريم",
    "detail": "Arabic — Uthmani Script",
    "icon": "quran",
}
_SRC_ENGLISH = {
    "type": "quran",
    "label": "Sahih International",
    "detail": "English Translation",
    "icon": "translation_en",
}
_SRC_URDU = {
    "type": "quran",
    "label": "Muhammad Ibrahim Junagarhi",
    "detail": "Urdu Translation — محمد ابراہیم جونا گڑھی",
    "icon": "translation_ur",
}
_SRC_KASHMIRI = {
    "type": "quran",
    "label": "Ather Managami",
    "detail": "Kashmiri Tafsir — اَتھَر مانَگامی",
    "icon": "translation_ks",
}
_SRC_AI = {
    "type": "ai_generated",
    "label": "Sirat Assistant",
    "detail": "Groq GPT-OSS-20B",
    "icon": "ai",
}
_SRC_KB = {
    "type": "knowledge_base",
    "label": "SiratSync Knowledge Base",
    "detail": "Verified Islamic content database",
    "icon": "database",
}


def _reply_has(reply: str, pattern: str) -> bool:
    """Check if reply contains a pattern (case-insensitive)."""
    return bool(re.search(pattern, reply, re.IGNORECASE))


def _has_arabic_text(reply: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", reply))


def _has_urdu_text(reply: str) -> bool:
    return _reply_has(reply, r"\b(Urdu|اردو)\s*:")


def _has_kashmiri_text(reply: str) -> bool:
    return _reply_has(reply, r"(Kashmiri|🏔️|کٲشُر|كشميري)\s*:")


def _has_english_translation(reply: str) -> bool:
    return _reply_has(reply, r"\b(English)\s*:")


def _build_sources(
    reply: str,
    is_verse_query: bool,
    is_quran_topic: bool,
    used_rag: bool,
    was_quick_reply: bool,
) -> list[dict]:
    """
    Build accurate source attribution based on:
    - What type of query was made
    - What is actually present in the reply text
    """
    sources: list[dict] = []

    if is_verse_query:
        if _has_arabic_text(reply):
            sources.append(_SRC_ARABIC)
        if _has_english_translation(reply):
            sources.append(_SRC_ENGLISH)
        if _has_urdu_text(reply):
            sources.append(_SRC_URDU)
        if _has_kashmiri_text(reply):
            sources.append(_SRC_KASHMIRI)
        if not sources:
            sources = [_SRC_ARABIC, _SRC_ENGLISH]
        return sources

    if is_quran_topic and used_rag:
        if _has_arabic_text(reply):
            sources.append(_SRC_ARABIC)
        if _has_english_translation(reply):
            sources.append(_SRC_ENGLISH)
        if _has_urdu_text(reply):
            sources.append(_SRC_URDU)
        if _has_kashmiri_text(reply):
            sources.append(_SRC_KASHMIRI)
        sources.append(_SRC_AI)
        if not sources or sources == [_SRC_AI]:
            sources = [_SRC_KB, _SRC_AI]
        return sources

    # Quick reply (app info, features, direct answers)
    if was_quick_reply:
        sources.append(_SRC_KB)
        return sources

    # Knowledge base answered without LLM
    if used_rag and not is_quran_topic:
        sources.append(_SRC_KB)
        sources.append(_SRC_AI)
        return sources

    # Pure LLM response
    sources.append(_SRC_AI)
    return sources

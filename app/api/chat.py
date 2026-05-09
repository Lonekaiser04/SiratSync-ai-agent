import re
import json as json_module
import logging
from datetime import datetime
from fastapi import APIRouter, Request
from app.models.request_models import ChatRequest
from app.models.response_models import ChatResponse
from app.services.rag_service import rag_service
from app.services.memory_service import memory
from app.services.intent_service import intent_detector
from app.utils.cache import cache
from app.utils.helpers import (
    get_quick_response,
    get_features_response,
    _call_llm_with_rag,
)
from app.prompts.system_prompt import SYSTEM_PROMPT
from groq import Groq
import os

logger = logging.getLogger(__name__)

router = APIRouter()

llm = Groq(api_key=os.environ.get("GROQ_API_KEY"))
def _is_verse_or_surah_query(message_lower: str, rag_svc) -> bool:
    """Returns True if the message is asking for a specific verse or surah — RAG must handle it."""
    import re
    # Pattern: "surah X verse Y", "surah al baqarah verse 115", "2:255", etc.
    if re.search(r"(?:surah|surat|chapter)\s+[\w\s\-]+\s+(?:verse|ayat|ayah)\s+\d+", message_lower):
        return True
    if re.search(r"\b([1-9]|[1-9]\d|1[01]\d|114):([1-9]\d{0,2})\b", message_lower):
        return True
    if re.search(r"(?:surah|surat)\s+\d{1,3}\b", message_lower):
        return True
    # Plain surah name lookup: "surah naba", "surah fatiha"
    if re.search(r"^(?:surah|surat)\s+[a-z\s\-]+$", message_lower.strip()):
        return True
    return False
@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        logger.info(f"📨 Chat from user {request.user_id}")

        cached_response = cache.get(request.message, request.user_id)
        if cached_response:
            logger.info(f"⚡ Cache hit — stats: {cache.stats}")
            return ChatResponse(**json_module.loads(cached_response))

        memory.add_message(request.user_id, "user", request.message)

        server_context       = memory.get_context(request.user_id, max_messages=6)
        conversation_context = request.context if request.context else server_context
        last_question        = memory.get_last_question(request.user_id)

        intent_result  = intent_detector.detect(request.message)
        primary_intent = intent_result["primary_intent"]
        sub_intent     = intent_result.get("sub_intent")
        sentiment      = intent_result.get("sentiment", "neutral")
        urgency        = intent_result.get("urgency", "low")

        message_lower = request.message.lower().strip()
        CONFIRM_WORDS = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "alright", "yes please"}

        if message_lower in CONFIRM_WORDS:
            lq = (last_question or "").lower()
            cc = (conversation_context or "").lower()
            if "features" in lq or "learn more" in lq or "features" in cc:
                primary_intent = "app_features_inquiry"
            elif "salah" in lq or "prayer" in lq:
                primary_intent, sub_intent = "salah", "learn_more"
            elif "quran" in lq:
                primary_intent, sub_intent = "quran", "learn_more"

        logger.info(f"🎯 Intent: {primary_intent} | Sub: {sub_intent} | Sentiment: {sentiment}")

        knowledge = rag_service.retrieve(request.message, top_k=5)

        user_profile              = memory.get_user_profile(request.user_id)
        user_profile["urgency"]   = urgency
        user_profile["sentiment"] = sentiment

        quick_reply = get_quick_response(
            request.message,
            primary_intent,
            sub_intent,
            user_profile,
            context=conversation_context,
            last_question=last_question,
            user_id=request.user_id,
        )

        if quick_reply:
            reply = quick_reply
            logger.info("⚡ Quick response used")

        # ✅ PRIORITY: Always intercept verse/surah references — never let LLM handle these
        elif _is_verse_or_surah_query(message_lower, rag_service):
            reply = rag_service.retrieve(request.message, top_k=5)
            logger.info("📖 Verse/Surah RAG response used — LLM bypassed")

        # ✅ Quran topic query — show exact verses + LLM explanation below
        elif rag_service._is_quran_topic_query(message_lower):
            reply = knowledge or rag_service.retrieve(request.message, top_k=5)
            logger.info("📚 Quran topic RAG response used")
        else:
            prompt = SYSTEM_PROMPT.format(
                context      = conversation_context or "(No previous conversation)",
                user_profile = json_module.dumps(user_profile, indent=2),
                knowledge    = knowledge or "(No specific knowledge retrieved)",
                question     = request.message,
            )

            temperature = 0.3 if primary_intent in ["technical", "factual"] else 0.6
            max_tokens = 350 if urgency == "high" else 500

            llm_response = llm.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user",   "content": request.message},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )

            reply = llm_response.choices[0].message.content.strip()

            if len(reply) > 2000 and urgency != "high":
                cutoff = reply.rfind('.', 0, 2000)
                if cutoff == -1:
                    cutoff = 2000
                reply = reply[:cutoff + 1] + "\n\n_📲 Open the app for the full response._"

            logger.info(f"🤖 LLM reply generated ({len(reply)} chars)")

        from app.services.action_service import suggest_actions, get_motivational_quote, get_quick_reply_suggestions

        actions     = suggest_actions(primary_intent, user_profile, sub_intent=sub_intent, sentiment=sentiment)
        suggestions = get_quick_reply_suggestions(primary_intent, sub_intent)

        motivational_quote = None
        if primary_intent == "struggling" or user_profile.get("consistency") == "struggling":
            motivational_quote = get_motivational_quote("struggling")
        elif primary_intent == "consistent" or user_profile.get("consistency") == "high":
            motivational_quote = get_motivational_quote("high")
        elif user_profile.get("consistency") == "medium":
            motivational_quote = get_motivational_quote("medium")

        memory.add_message(request.user_id, "assistant", reply)

        is_verse_query  = _is_verse_or_surah_query(message_lower, rag_service)
        is_quran_topic  = rag_service._is_quran_topic_query(message_lower)
        used_rag        = bool(knowledge and knowledge != "(No specific knowledge retrieved)")

        sources = _build_sources(
            reply=reply,
            is_verse_query=is_verse_query,
            is_quran_topic=is_quran_topic,
            used_rag=used_rag,
            was_quick_reply=bool(quick_reply),
        )

        response_data = {
            "reply":              reply,
            "intent":             primary_intent,
            "sub_intent":         sub_intent,
            "sentiment":          sentiment,
            "actions":            actions,
            "suggestions":        suggestions[:4],
            "motivational_quote": motivational_quote,
            "timestamp":          datetime.now().isoformat(),
            "sources":            sources,   # ✅ NEW
        }

        # response_data = {
        #     "reply":              reply,
        #     "intent":             primary_intent,
        #     "sub_intent":         sub_intent,
        #     "sentiment":          sentiment,
        #     "actions":            actions,
        #     "suggestions":        suggestions[:4],
        #     "motivational_quote": motivational_quote,
        #     "timestamp":          datetime.now().isoformat(),
        # }

        cache.set(request.message, request.user_id, json_module.dumps(response_data), ttl_minutes=60)

        return ChatResponse(**response_data)

    except Exception as e:
        logger.error(f"❌ Chat error: {e}", exc_info=True)
        return ChatResponse(
            reply=(
                "I'm having trouble processing your request right now. "
                "Please try again in a moment. JazakAllah khair for your patience. 🤲"
            ),
            intent="error",
            sub_intent=None,
            sentiment="neutral",
            actions={"reminders": [], "habits": [], "duas": [], "quick_actions": []},
            suggestions=["Try again", "Browse Quran", "Check prayer times", "Contact support"],
            motivational_quote=None,
            timestamp=datetime.now().isoformat(),
        )
# ── Source definitions (single source of truth) ───────────────────────────────
_SRC_ARABIC = {
    "type":      "quran",
    "label":     "القرآن الكريم",
    "detail":    "Arabic — Uthmani Script",
    "icon":      "quran",
}
_SRC_ENGLISH = {
    "type":      "quran",
    "label":     "Sahih International",
    "detail":    "English Translation",
    "icon":      "translation_en",
}
_SRC_URDU = {
    "type":      "quran",
    "label":     "Muhammad Ibrahim Junagarhi",
    "detail":    "Urdu Translation — محمد ابراہیم جونا گڑھی",
    "icon":      "translation_ur",
}
_SRC_KASHMIRI = {
    "type":      "quran",
    "label":     "Ather Managami",
    "detail":    "Kashmiri Tafsir — اَتھَر مانَگامی",
    "icon":      "translation_ks",
}
_SRC_AI = {
    "type":      "ai_generated",
    "label":     "SiratSync AI",
    "detail":    "Groq LLaMA 3.1-8b",
    "icon":      "ai",
}
_SRC_KB = {
    "type":      "knowledge_base",
    "label":     "SiratSync Knowledge Base",
    "detail":    "Verified Islamic content database",
    "icon":      "database",
}


def _reply_has(reply: str, pattern: str) -> bool:
    """Check if reply contains a pattern (case-insensitive)."""
    return bool(re.search(pattern, reply, re.IGNORECASE))


def _has_arabic_text(reply: str) -> bool:
    return bool(re.search(r'[\u0600-\u06FF]', reply))


def _has_urdu_text(reply: str) -> bool:
    # Urdu label appears in reply when RAG returns verse data
    return _reply_has(reply, r'\b(Urdu|اردو)\s*:')


def _has_kashmiri_text(reply: str) -> bool:
    return _reply_has(reply, r'(Kashmiri|🏔️|کٲشُر|كشميري)\s*:')


def _has_english_translation(reply: str) -> bool:
    return _reply_has(reply, r'\b(English)\s*:')


def _build_sources(
    reply: str,
    is_verse_query: bool,
    is_quran_topic: bool,
    used_rag: bool,
    was_quick_reply: bool,
) -> list:
    """
    Build accurate source attribution based on:
    - What type of query was made
    - What is actually present in the reply text
    """
    sources = []

    # ── Case 1: Specific verse or surah lookup ────────────────────────────────
    if is_verse_query:
        # Arabic is always present for verse lookups
        if _has_arabic_text(reply):
            sources.append(_SRC_ARABIC)
        # Only add translation sources if they actually appear in the reply
        if _has_english_translation(reply):
            sources.append(_SRC_ENGLISH)
        if _has_urdu_text(reply):
            sources.append(_SRC_URDU)
        if _has_kashmiri_text(reply):
            sources.append(_SRC_KASHMIRI)
        # If nothing detected but it's a verse query, at least show Arabic + English
        if not sources:
            sources = [_SRC_ARABIC, _SRC_ENGLISH]
        return sources

    # ── Case 2: Quran topic query (marriage, parents, etc.) ───────────────────
    if is_quran_topic and used_rag:
        if _has_arabic_text(reply):
            sources.append(_SRC_ARABIC)
        if _has_english_translation(reply):
            sources.append(_SRC_ENGLISH)
        if _has_urdu_text(reply):
            sources.append(_SRC_URDU)
        if _has_kashmiri_text(reply):
            sources.append(_SRC_KASHMIRI)
        # AI explanation is added when topic query goes through LLM explanation
        sources.append(_SRC_AI)
        if not sources or sources == [_SRC_AI]:
            # Fallback: topic was retrieved from KB, not verse data
            sources = [_SRC_KB, _SRC_AI]
        return sources

    # ── Case 3: Quick reply (app info, features, direct answers) ─────────────
    if was_quick_reply:
        sources.append(_SRC_KB)
        return sources

    # ── Case 4: Knowledge base answered without LLM ───────────────────────────
    if used_rag and not is_quran_topic:
        sources.append(_SRC_KB)
        sources.append(_SRC_AI)
        return sources

    # ── Case 5: Pure LLM response ─────────────────────────────────────────────
    sources.append(_SRC_AI)
    return sources
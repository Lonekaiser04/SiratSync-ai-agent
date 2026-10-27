"""
Primary chat endpoint.

Pipeline: cache check -> memory write -> intent detection -> RAG retrieval
-> quick-reply short-circuit OR LLM generation -> action suggestions ->
response assembly + caching.
"""
from __future__ import annotations

import asyncio
import json as json_module
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from groq import AsyncGroq, GroqError, NotFoundError

from app.core.config import settings
from app.core.security import detect_prompt_injection, sanitize_user_text
from app.models.request_models import ChatRequest
from app.models.response_models import ActionsPayload, ChatResponse
from app.prompts.system_prompt import SYSTEM_PROMPT
from app.services.intent_service import intent_detector
from app.services.llm_service import LLMStreamChunk, llm_service
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

    effective_user_id = getattr(http_request.state, "authenticated_user_id", None) or request.user_id

    try:
        logger.info("request_id=%s Chat from user %s", request_id, effective_user_id)

        cached_response = await cache.get(request.message, effective_user_id)
        if cached_response:
            logger.info("request_id=%s Cache hit — stats: %s", request_id, cache.stats)
            try:
                return ChatResponse(**json_module.loads(cached_response))
            except (json_module.JSONDecodeError, TypeError, ValueError) as e:
                # Corrupt cache entry shouldn't take down the request — log
                # and fall through to a fresh generation.
                logger.warning("request_id=%s Corrupt cache entry, regenerating: %s", request_id, e)

        # Capture prior conversational context and previous turns BEFORE generating current response
        last_question = await memory.get_last_question(effective_user_id, exclude_current=request.message)
        last_bot_message = await memory.get_last_bot_message(effective_user_id)
        recent_messages = await memory.get_recent_messages(effective_user_id, count=6)
        server_context = await memory.get_context(effective_user_id, max_messages=6)
        conversation_context = request.context if request.context else server_context

        if detect_prompt_injection(request.message) or (
            request.context and detect_prompt_injection(request.context)
        ):
            logger.warning(
                "request_id=%s Possible prompt injection pattern detected for user %s",
                request_id, effective_user_id,
            )

        safe_message = sanitize_user_text(request.message, max_length=settings.MAX_MESSAGE_LENGTH)
        safe_context = (
            sanitize_user_text(conversation_context, max_length=settings.MAX_CONTEXT_LENGTH)
            if conversation_context
            else conversation_context
        )

        # Deduplicate trailing current message if client context already included it
        if safe_context and safe_message:
            context_lines = [line for line in safe_context.split("\n") if line.strip()]
            if context_lines and (
                context_lines[-1].lower() == safe_message.lower()
                or context_lines[-1].lower() == f"user: {safe_message.lower()}"
                or context_lines[-1].lower().endswith(safe_message.lower())
            ):
                context_lines.pop()
            safe_context = "\n".join(context_lines) if context_lines else None

        intent_result = intent_detector.detect(request.message)
        primary_intent = intent_result.primary_intent
        sub_intent = intent_result.sub_intent
        sentiment = intent_result.sentiment
        urgency = intent_result.urgency

        message_lower = request.message.lower().strip()

        if message_lower in _CONFIRM_WORDS or message_lower in {"tell me more", "learn more", "more details", "what else"}:
            lq = (last_question or "").lower()
            lbm = (last_bot_message or "").lower()
            cc = (conversation_context or "").lower()
            if "features" in lbm or "features" in lq or "learn more" in lbm or "features" in cc:
                primary_intent = "app_features_inquiry"
            elif "salah" in lbm or "salah" in lq or "prayer" in lbm or "prayer" in lq:
                primary_intent, sub_intent = "salah", "learn_more"
            elif "quran" in lbm or "quran" in lq:
                primary_intent, sub_intent = "quran", "learn_more"
            elif "hadith" in lbm or "hadith" in lq:
                primary_intent, sub_intent = "hadith", "learn_more"

        logger.info(
            "request_id=%s Intent: %s | Sub: %s | Sentiment: %s",
            request_id, primary_intent, sub_intent, sentiment,
        )

        knowledge = await asyncio.to_thread(
            rag_service.retrieve, request.message, 5, effective_user_id
        )
        if not knowledge or knowledge.strip() == "(No specific knowledge retrieved)":
            knowledge = ""

        user_profile = await memory.get_user_profile(effective_user_id)
        user_profile["urgency"] = urgency
        user_profile["sentiment"] = sentiment

        quick_reply = await get_quick_response(
            request.message,
            primary_intent,
            sub_intent,
            user_profile,
            context=conversation_context,
            last_question=last_question,
            user_id=effective_user_id,
        )

        used_llm = False
        effective_model = settings.GROQ_MODEL

        if quick_reply:
            reply = quick_reply
            logger.info("request_id=%s Quick response used", request_id)

        elif _is_verse_or_surah_query(message_lower):
            reply = await asyncio.to_thread(
                rag_service.retrieve, request.message, 5, request.user_id
            )
            logger.info("request_id=%s Verse/Surah RAG response used — LLM bypassed", request_id)

        else:
            prompt = SYSTEM_PROMPT.format(
                context=safe_context or "(No previous conversation)",
                user_profile=json_module.dumps(user_profile, indent=2),
                knowledge=knowledge or "(No specific knowledge retrieved)",
                question=safe_message,
            )

            # Construct messages array preserving multi-turn context
            llm_messages = [{"role": "system", "content": prompt}]
            if recent_messages:
                for msg in recent_messages:
                    m_role = msg.get("role")
                    m_content = (msg.get("content") or "").strip()
                    if m_role in ("user", "assistant") and m_content:
                        if m_role == "user" and m_content.lower() == safe_message.lower():
                            continue
                        llm_messages.append({"role": m_role, "content": m_content})
            llm_messages.append({"role": "user", "content": safe_message})

            temperature = 0.3 if primary_intent in ("technical", "factual") else 0.6
            max_tokens = 700 if urgency == "high" else 1500

            try:
                llm_result = await llm_service.generate_completion(
                    messages=llm_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    client=llm,
                    request_id=request_id,
                )
                effective_model = llm_result.model_used
                reply = llm_result.content
                if llm_result.is_fallback:
                    logger.warning(
                        "request_id=%s Configured Groq model %s not found (404). Falling back to %s",
                        request_id,
                        settings.GROQ_MODEL,
                        effective_model,
                    )
                if reply:
                    used_llm = True
                else:
                    logger.warning("request_id=%s LLM returned empty content", request_id)
                    reply = (
                        "I wasn't able to form a complete answer to that. Could you "
                        "rephrase your question? 🤲"
                    )
                    used_llm = False

            except GroqError as e:
                logger.error("request_id=%s Groq API error: %s", request_id, e, exc_info=True)
                reply = (
                    "I'm having trouble reaching my knowledge service right now. "
                    "Please try again shortly. JazakAllah khair for your patience. 🤲"
                )
                used_llm = False
            except Exception as e:
                logger.error("request_id=%s Unexpected error during LLM generation: %s", request_id, e, exc_info=True)
                reply = (
                    "I'm having trouble reaching my knowledge service right now. "
                    "Please try again shortly. JazakAllah khair for your patience. 🤲"
                )
                used_llm = False

            if len(reply) > 2000 and urgency != "high":
                cutoff = reply.rfind(".", 0, 2000)
                if cutoff != -1:
                    reply = reply[: cutoff + 1].strip()
                else:
                    reply = reply[:2000].strip()

            if used_llm:
                logger.info(
                    "request_id=%s LLM reply generated successfully (%d chars) using model %s",
                    request_id,
                    len(reply),
                    effective_model,
                )
            else:
                logger.warning(
                    "request_id=%s Fallback response returned (%d chars) due to provider failure or empty generation",
                    request_id,
                    len(reply),
                )

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
        if primary_intent == "struggling" or (user_profile.get("consistency") == "struggling" and sentiment == "negative"):
            motivational_quote = get_motivational_quote("struggling")
        elif primary_intent == "consistent" or user_profile.get("consistency") == "high":
            motivational_quote = get_motivational_quote("high")
        elif user_profile.get("consistency") == "medium":
            motivational_quote = get_motivational_quote("medium")

        # Update memory after successful response generation
        await memory.add_message(effective_user_id, "user", request.message)
        await memory.add_message(effective_user_id, "assistant", reply)

        is_verse_query = _is_verse_or_surah_query(message_lower)
        is_quran_topic = rag_service._is_quran_topic_query(message_lower)
        used_rag = bool(knowledge and knowledge != "(No specific knowledge retrieved)")

        sources = _build_sources(
            reply=reply,
            is_verse_query=is_verse_query,
            is_quran_topic=is_quran_topic,
            used_rag=used_rag,
            was_quick_reply=bool(quick_reply),
            used_llm=used_llm,
            model_name=effective_model if not quick_reply else settings.GROQ_MODEL,
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

        if used_llm or quick_reply:
            try:
                await cache.set(
                    request.message,
                    effective_user_id,
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
    "detail": f"Groq {settings.GROQ_MODEL}",
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
    used_llm: bool = True,
    model_name: str | None = None,
) -> list[dict]:
    """
    Build accurate source attribution based on:
    - What type of query was made
    - What is actually present in the reply text
    - Whether LLM was actually used or a fallback/quick-reply was returned
    """
    sources: list[dict] = []

    ai_source = {
        "type": "ai_generated",
        "label": "Sirat Assistant",
        "detail": f"Groq {model_name or settings.GROQ_MODEL}",
        "icon": "ai",
    }

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
        if used_llm:
            sources.append(ai_source)
        if not sources or sources == [ai_source]:
            sources = [_SRC_KB, ai_source] if used_llm else [_SRC_KB]
        return sources

    # Quick reply (app info, features, direct answers)
    if was_quick_reply:
        sources.append(_SRC_KB)
        return sources

    # Knowledge base answered without LLM (or with LLM)
    if used_rag and not is_quran_topic:
        sources.append(_SRC_KB)
        if used_llm:
            sources.append(ai_source)
        return sources

    # Pure LLM response vs fallback
    if used_llm:
        sources.append(ai_source)
    else:
        sources.append(_SRC_KB)
    return sources


def _format_sse(event: str, data: dict | list | str) -> str:
    if isinstance(data, (dict, list)):
        payload = json_module.dumps(data)
    else:
        payload = json_module.dumps({"delta": data}) if event == "token" else str(data)
    lines = payload.split("\n")
    data_lines = "\n".join(f"data: {l}" for l in lines)
    return f"event: {event}\n{data_lines}\n\n"


async def _chat_stream_generator(request: ChatRequest, http_request: Request):
    request_id = getattr(http_request.state, "request_id", "unknown")
    effective_user_id = getattr(http_request.state, "authenticated_user_id", None) or request.user_id

    try:
        logger.info("request_id=%s Streaming chat request from user %s", request_id, effective_user_id)

        # Emit connection acknowledgement immediately so the client's idle
        # timeout resets BEFORE any slow backend work (cache, memory, RAG).
        yield _format_sse("status", {"status": "connected", "stage": "init"})

        # 1. Cache check
        cached_response = await cache.get(request.message, effective_user_id)
        if cached_response:
            logger.info("request_id=%s Cache hit for stream — stats: %s", request_id, cache.stats)
            try:
                cached_data = json_module.loads(cached_response)
                yield _format_sse("status", {"status": "cached", "stage": "cache_hit"})
                yield _format_sse("token", {"delta": cached_data.get("reply", "")})
                yield _format_sse("done", cached_data)
                return
            except (json_module.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning("request_id=%s Corrupt cache entry during stream, regenerating: %s", request_id, e)

        # 2. Context & memory extraction (non-fatal: degrade gracefully on Redis failure)
        try:
            last_question = await memory.get_last_question(effective_user_id, exclude_current=request.message)
            last_bot_message = await memory.get_last_bot_message(effective_user_id)
            recent_messages = await memory.get_recent_messages(effective_user_id, count=6)
            server_context = await memory.get_context(effective_user_id, max_messages=6)
        except Exception as mem_err:
            logger.warning(
                "request_id=%s Memory retrieval failed, continuing with empty context: %s",
                request_id, mem_err,
            )
            last_question = None
            last_bot_message = None
            recent_messages = []
            server_context = ""
        conversation_context = request.context if request.context else server_context

        # 3. Security & sanitization
        if detect_prompt_injection(request.message) or (
            request.context and detect_prompt_injection(request.context)
        ):
            logger.warning(
                "request_id=%s Possible prompt injection pattern detected in stream for user %s",
                request_id, effective_user_id,
            )

        safe_message = sanitize_user_text(request.message, max_length=settings.MAX_MESSAGE_LENGTH)
        safe_context = (
            sanitize_user_text(conversation_context, max_length=settings.MAX_CONTEXT_LENGTH)
            if conversation_context
            else conversation_context
        )

        if safe_context and safe_message:
            context_lines = [line for line in safe_context.split("\n") if line.strip()]
            if context_lines and (
                context_lines[-1].lower() == safe_message.lower()
                or context_lines[-1].lower() == f"user: {safe_message.lower()}"
                or context_lines[-1].lower().endswith(safe_message.lower())
            ):
                context_lines.pop()
            safe_context = "\n".join(context_lines) if context_lines else None

        # 4. Intent detection
        intent_result = intent_detector.detect(request.message)
        primary_intent = intent_result.primary_intent
        sub_intent = intent_result.sub_intent
        sentiment = intent_result.sentiment
        urgency = intent_result.urgency

        message_lower = request.message.lower().strip()

        if message_lower in _CONFIRM_WORDS or message_lower in {"tell me more", "learn more", "more details", "what else"}:
            lq = (last_question or "").lower()
            lbm = (last_bot_message or "").lower()
            cc = (conversation_context or "").lower()
            if "features" in lbm or "features" in lq or "learn more" in lbm or "features" in cc:
                primary_intent = "app_features_inquiry"
            elif "salah" in lbm or "salah" in lq or "prayer" in lbm or "prayer" in lq:
                primary_intent, sub_intent = "salah", "learn_more"
            elif "quran" in lbm or "quran" in lq:
                primary_intent, sub_intent = "quran", "learn_more"
            elif "hadith" in lbm or "hadith" in lq:
                primary_intent, sub_intent = "hadith", "learn_more"

        yield _format_sse("meta", {
            "intent": primary_intent,
            "sub_intent": sub_intent,
            "sentiment": sentiment,
            "urgency": urgency,
        })

        # 5. Non-blocking RAG retrieval
        yield _format_sse("status", {"status": "searching", "stage": "knowledge_retrieval"})
        knowledge = await asyncio.to_thread(
            rag_service.retrieve, request.message, 5, effective_user_id
        )
        if not knowledge or knowledge.strip() == "(No specific knowledge retrieved)":
            knowledge = ""

        user_profile = await memory.get_user_profile(effective_user_id)
        user_profile["urgency"] = urgency
        user_profile["sentiment"] = sentiment

        # 6. Quick reply check
        quick_reply = await get_quick_response(
            request.message,
            primary_intent,
            sub_intent,
            user_profile,
            context=conversation_context,
            last_question=last_question,
            user_id=effective_user_id,
        )

        used_llm = False
        effective_model = settings.GROQ_MODEL
        reply = ""

        if quick_reply:
            reply = quick_reply
            logger.info("request_id=%s Quick response used for stream", request_id)
            yield _format_sse("status", {"status": "generating", "stage": "quick_reply"})
            words = quick_reply.split(" ")
            for i, word in enumerate(words):
                if await http_request.is_disconnected():
                    logger.info("request_id=%s Client disconnected during quick reply stream", request_id)
                    return
                space = " " if i < len(words) - 1 else ""
                yield _format_sse("token", {"delta": word + space})

        elif _is_verse_or_surah_query(message_lower):
            reply = await asyncio.to_thread(
                rag_service.retrieve, request.message, 5, request.user_id
            )
            logger.info("request_id=%s Verse/Surah RAG response used for stream", request_id)
            yield _format_sse("status", {"status": "generating", "stage": "verse_retrieval"})
            lines = reply.split("\n")
            for i, line in enumerate(lines):
                if await http_request.is_disconnected():
                    logger.info("request_id=%s Client disconnected during verse stream", request_id)
                    return
                nl = "\n" if i < len(lines) - 1 else ""
                yield _format_sse("token", {"delta": line + nl})

        else:
            prompt = SYSTEM_PROMPT.format(
                context=safe_context or "(No previous conversation)",
                user_profile=json_module.dumps(user_profile, indent=2),
                knowledge=knowledge or "(No specific knowledge retrieved)",
                question=safe_message,
            )

            llm_messages = [{"role": "system", "content": prompt}]
            if recent_messages:
                for msg in recent_messages:
                    m_role = msg.get("role")
                    m_content = (msg.get("content") or "").strip()
                    if m_role in ("user", "assistant") and m_content:
                        if m_role == "user" and m_content.lower() == safe_message.lower():
                            continue
                        llm_messages.append({"role": m_role, "content": m_content})
            llm_messages.append({"role": "user", "content": safe_message})

            temperature = 0.3 if primary_intent in ("technical", "factual") else 0.6
            max_tokens = 700 if urgency == "high" else 1500

            yield _format_sse("status", {"status": "thinking", "stage": "llm_generation"})

            accumulated: list[str] = []
            queue: asyncio.Queue[LLMStreamChunk | Exception | None] = asyncio.Queue()

            async def _stream_producer():
                try:
                    async for chunk in llm_service.generate_completion_stream(
                        messages=llm_messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        client=llm,
                        request_id=request_id,
                    ):
                        await queue.put(chunk)
                except Exception as exc:
                    await queue.put(exc)
                finally:
                    await queue.put(None)

            producer_task = asyncio.create_task(_stream_producer())
            last_token_time = asyncio.get_event_loop().time()
            stall_timeout = float(settings.LLM_TIMEOUT_SECONDS)
            heartbeat_interval = min(5.0, max(0.2, stall_timeout / 2.0))

            try:
                while True:
                    if await http_request.is_disconnected():
                        logger.info("request_id=%s Client disconnected during LLM stream", request_id)
                        producer_task.cancel()
                        return

                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                    except asyncio.TimeoutError:
                        if await http_request.is_disconnected():
                            logger.info("request_id=%s Client disconnected during stream heartbeat wait", request_id)
                            producer_task.cancel()
                            return
                        if (asyncio.get_event_loop().time() - last_token_time) >= stall_timeout:
                            logger.error(
                                "request_id=%s LLM streaming stalled: no tokens for %ds",
                                request_id,
                                stall_timeout,
                            )
                            producer_task.cancel()
                            raise TimeoutError(f"LLM streaming provider timed out after {stall_timeout}s")
                        # Emit keep-alive comment line to prevent mobile proxy/gateway timeouts
                        yield ": keep-alive\n\n"
                        continue

                    if item is None:
                        break
                    if isinstance(item, Exception):
                        raise item

                    chunk = item
                    last_token_time = asyncio.get_event_loop().time()
                    accumulated.append(chunk.delta)
                    effective_model = chunk.model_used
                    yield _format_sse("token", {"delta": chunk.delta})

                reply = "".join(accumulated).strip()
                if reply:
                    used_llm = True
                else:
                    logger.warning("request_id=%s LLM returned empty stream", request_id)
                    reply = (
                        "I wasn't able to form a complete answer to that. Could you "
                        "rephrase your question? 🤲"
                    )
                    yield _format_sse("token", {"delta": reply})
                    used_llm = False

            except GroqError as e:
                logger.error("request_id=%s Groq API error during stream: %s", request_id, e, exc_info=True)
                reply = (
                    "I'm having trouble reaching my knowledge service right now. "
                    "Please try again shortly. JazakAllah khair for your patience. 🤲"
                )
                yield _format_sse("token", {"delta": reply})
                used_llm = False
            except Exception as e:
                logger.error("request_id=%s Unexpected error during LLM streaming: %s", request_id, e, exc_info=True)
                reply = (
                    "I'm having trouble reaching my knowledge service right now. "
                    "Please try again shortly. JazakAllah khair for your patience. 🤲"
                )
                yield _format_sse("token", {"delta": reply})
                used_llm = False
            finally:
                if not producer_task.done():
                    producer_task.cancel()

            if len(reply) > 2000 and urgency != "high":
                cutoff = reply.rfind(".", 0, 2000)
                if cutoff != -1:
                    reply = reply[: cutoff + 1].strip()
                else:
                    reply = reply[:2000].strip()

        # 7. Suggestions, actions, quotes
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
        if primary_intent == "struggling" or (user_profile.get("consistency") == "struggling" and sentiment == "negative"):
            motivational_quote = get_motivational_quote("struggling")
        elif primary_intent == "consistent" or user_profile.get("consistency") == "high":
            motivational_quote = get_motivational_quote("high")
        elif user_profile.get("consistency") == "medium":
            motivational_quote = get_motivational_quote("medium")

        # 8. Save complete response to memory only after successful generation
        if not await http_request.is_disconnected():
            await memory.add_message(effective_user_id, "user", request.message)
            await memory.add_message(effective_user_id, "assistant", reply)

        is_verse_query = _is_verse_or_surah_query(message_lower)
        is_quran_topic = rag_service._is_quran_topic_query(message_lower)
        used_rag = bool(knowledge and knowledge != "(No specific knowledge retrieved)")

        sources = _build_sources(
            reply=reply,
            is_verse_query=is_verse_query,
            is_quran_topic=is_quran_topic,
            used_rag=used_rag,
            was_quick_reply=bool(quick_reply),
            used_llm=used_llm,
            model_name=effective_model if not quick_reply else settings.GROQ_MODEL,
        )

        actions_dict = actions.model_dump() if hasattr(actions, "model_dump") else actions.dict() if hasattr(actions, "dict") else actions

        response_data = {
            "reply": reply,
            "intent": primary_intent,
            "sub_intent": sub_intent,
            "sentiment": sentiment,
            "actions": actions_dict,
            "suggestions": suggestions[:4],
            "motivational_quote": motivational_quote,
            "timestamp": datetime.now().isoformat(),
            "sources": sources,
        }

        if (used_llm or quick_reply) and not await http_request.is_disconnected():
            try:
                await cache.set(
                    request.message,
                    effective_user_id,
                    json_module.dumps(response_data),
                    ttl_minutes=settings.RESPONSE_CACHE_TTL_MINUTES,
                )
            except (TypeError, ValueError) as e:
                logger.warning("request_id=%s Failed to cache streaming response: %s", request_id, e)

        yield _format_sse("done", response_data)

    except Exception as e:
        logger.error("request_id=%s Unhandled stream error: %s", request_id, e, exc_info=True)
        fallback_msg = (
            "I'm having trouble processing your request right now. "
            "Please try again in a moment. JazakAllah khair for your patience. 🤲"
        )
        actions_dict = _fallback_actions().model_dump() if hasattr(_fallback_actions(), "model_dump") else _fallback_actions().dict()
        yield _format_sse("error", {
            "reply": fallback_msg,
            "error": str(e),
            "intent": "error",
            "sub_intent": None,
            "sentiment": "neutral",
            "actions": actions_dict,
            "suggestions": ["Try again", "Browse Quran", "Check prayer times", "Contact support"],
            "timestamp": datetime.now().isoformat(),
        })


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, http_request: Request):
    """
    Server-Sent Events (SSE) streaming chat endpoint.
    Emits events: 'status', 'meta', 'token', 'done', 'error'.
    Saves conversation memory only after successful generation.
    """
    return StreamingResponse(
        _chat_stream_generator(request, http_request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )



import re
import logging
from typing import Optional
from app.services.rag_service import rag_service
from app.services.memory_service import memory
from app.services.action_service import get_motivational_quote

logger = logging.getLogger(__name__)

def get_features_response() -> str:
    return """✨ **SiratSync Key Features**:

📖 **Quran Module** - Read with English, Kashmiri (Tafsir), and Urdu translations
🕌 **Prayer Times** - Accurate timings with Adhan notifications
📚 **Hadith** - Sahih Bukhari & Muslim collections
📿 **Duas & Adhkar** - Authentic supplications for daily situations
⭐ **Habit Tracker** - Track Salah, Quran, and Dhikr consistency
🧭 **Qibla Finder** - High-accuracy compass to Mecca
👥 **Community** - Peaceful Islamic social space
🌙 **Ramadan Mode** - Suhoor/Iftar timings and special duas
🎯 **Learn Salah** - Step-by-step prayer guide for beginners

Which feature would you like to explore first?"""

def _format_rag_data_direct(rag_data: str) -> str:
    lines_out = ["📖 **Quranic Guidance:**\n"]
    for line in rag_data.split("\n"):
        stripped = line.strip()
        if not stripped:
            lines_out.append("")
            continue
        if stripped.startswith("VERSE REFERENCE:"):
            ref = stripped.replace("VERSE REFERENCE:", "").strip()
            lines_out.append(f"\n**📍 {ref}**")
        elif stripped.startswith("SURAH:"):
            lines_out.append(f"\n**{stripped.replace('SURAH:', '📖').strip()}**")
        elif stripped.startswith("ARABIC:"):
            lines_out.append(f" {stripped.replace('ARABIC:', '').strip()}")
        elif stripped.startswith("ENGLISH:"):
            lines_out.append(f"{stripped.replace('ENGLISH:', '').strip()}_")
        elif stripped.startswith("URDU:"):
            lines_out.append(f"{stripped.replace('URDU:', '').strip()}")
        elif stripped.startswith("KASHMIRI TAFSIR:") or stripped.startswith("KASHMIRI:"):
            ks = re.sub(r"^KASHMIRI( TAFSIR)?:", "", stripped).strip()
            lines_out.append(f"🏔️ **Kashmiri:** {ks}")
        elif stripped.startswith("TRANSLITERATION:"):
            lines_out.append(f"🔊 _{stripped.replace('TRANSLITERATION:', '').strip()}_")
        elif stripped.startswith("SUMMARY:"):
            lines_out.append(f"📝 {stripped.replace('SUMMARY:', '').strip()}")
        elif stripped.startswith("MAIN TOPICS:"):
            lines_out.append(f"📌 **Topics:** {stripped.replace('MAIN TOPICS:', '').strip()}")
        elif stripped.startswith("VERSES:"):
            lines_out.append(f"📊 {stripped}")
        elif stripped.startswith("SIMILAR VERSES:"):
            lines_out.append(f"\n📎 **Similar Verses:**")
        elif stripped.startswith("  -"):
            lines_out.append(stripped)
        elif stripped.startswith("RELATED SURAHS:"):
            lines_out.append(f"\n📖 **Related Surahs:**")
        elif stripped.startswith("  -") or stripped.startswith("VERSE:"):
            lines_out.append(stripped.replace("VERSE:", "\n**Verse:**"))
        else:
            lines_out.append(stripped)

    lines_out.append("\n🤲 _Open the full surah in the app for complete tafsir._")
    return "\n".join(lines_out)

def _call_llm_with_rag(user_query: str, rag_data: str, user_profile: dict) -> str:
    from groq import Groq
    import os
    llm = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    english_only = _extract_english_only(rag_data)
    if not english_only.strip():
        return "I couldn't find relevant information in English."
    try:
        response = llm.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": """You are SiratSync AI, an Islamic assistant.

You will receive Quran reference data in English only.
Your job:
1. Answer the user's question using the provided data strictly
2. Reference verses properly (e.g., "Surah Al-Baqarah 2:255 says...")
3. Keep explanations clear and concise
4. Be scholarly but warm
5. NEVER attempt to write Arabic, Urdu, or Kashmiri text
6. Respond ONLY in English
7. Only use the information provided. Do not add, question, or correct it
8.End with: “📌 For accurate verse details, ask by reference (e.g., 94:5).”
""",
                },
                {
                    "role": "user", 
                    "content": f"Based on this information:\n\n{english_only}\n\nUser asks: {user_query}\n\nProvide a helpful English response:"
                },
            ],
            temperature=0.3,
            max_tokens=600,
        )
        english_response = response.choices[0].message.content.strip()
        logger.info(f"✅ English-only response generated ({len(english_response)} chars)")
        return english_response
    except Exception as e:
        logger.error(f"⚠️ LLM failed: {e}")
        return _format_rag_data_direct(rag_data)

def _extract_english_only(rag_data: str) -> str:
    english_lines = []
    for line in rag_data.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("VERSE REFERENCE:"):
            english_lines.append(stripped)
        elif stripped.startswith("ENGLISH:"):
            text = stripped.replace("ENGLISH:", "").strip()
            if text.startswith("_") and text.endswith("_"):
                text = text[1:-1]
            english_lines.append(text)
        elif stripped.startswith("SUMMARY:"):
            english_lines.append(stripped)
        elif stripped.startswith("MAIN TOPICS:"):
            english_lines.append(stripped)
        elif stripped.startswith("SURAH:"):
            english_lines.append(stripped)
        elif stripped.startswith("SURAH NUMBER:"):
            english_lines.append(stripped)
        elif stripped.startswith("VERSES:"):
            english_lines.append(stripped)
        elif stripped.startswith("REVELATION TYPE:"):
            english_lines.append(stripped)
        elif stripped.startswith("JUZ:"):
            english_lines.append(stripped)
        elif stripped.startswith("SIMILAR VERSES:"):
            english_lines.append(stripped)
        elif stripped.startswith("  -"):
            english_lines.append(stripped)
    return "\n".join(english_lines)

def get_quick_response(
    message:       str,
    intent:        str,
    sub_intent:    Optional[str],
    user_profile:  dict,
    context:       str = "",
    last_question: str = "",
    user_id:       str = "default",
) -> Optional[str]:
    message_lower = message.lower().strip()

    direct = rag_service.get_direct_answer(message)
    if direct:
        logger.info("⚡ Direct RAG answer (no LLM)")
        return direct

    followup = rag_service._handle_followup(message, message_lower, user_id=user_id)
    if followup:
        logger.info("⚡ Context-aware follow-up (no LLM)")
        return followup

    verse_ref = re.search(r'\b([1-9]|[1-9]\d|1[01]\d|114):([1-9]\d{0,2})\b', message_lower)
    if verse_ref:
        surah_id = int(verse_ref.group(1))
        verse_id = int(verse_ref.group(2))
        verse = rag_service.get_verse_by_reference(surah_id, verse_id)
        if verse:
            logger.info(f"⚡ Direct verse {surah_id}:{verse_id} — no LLM")
            return rag_service._handle_verse_reference_query(surah_id, verse_id)

    QURAN_QUERY_TRIGGERS = [
        "surah", "surat", "chapter",
        "what does quran say", "quran says", "quranic",
        "ayat about", "verses about", "according to quran",
        "what does islam say", "islamic view", "islamic ruling",
        "is it haram", "is it halal", "allah says",
        "quranic guidance", "quran on", "islam on",
        "kashmiri translation", "urdu translation",
        "show me in urdu", "show me in kashmiri",
        "translate to urdu", "translate to kashmiri",
        "similar ayahs", "similar verses", "related ayahs",
        "how many words", "how many letters", "how many verses",
        "how many ayat", "word count", "letter count", "verse count",
        "total words", "total letters", "total ayat",
        "how many surahs", "surahs in quran", "chapters in quran",
        "longest surah", "longest chapter", "longest surat",
        "most verses surah", "most verses chapter", "surah with most verses",
        "longest verse", "longest ayah", "longest ayat",
        "shortest verse", "shortest ayah", "shortest ayat",
        "total", "whole quran", "entire quran", "quran total",
        "juz", "para ", "parah",
        "sabr", "shukr", "tawakkul", "taqwa", "iman", "kufr",
        "shirk", "tawhid", "ibadat", "sunnah", "bidah", "jihad",
        "zulm", "adl", "kibr", "hasad", "ghayba", "namima",
        "siddiq", "tawadu", "nifaq", "munafiq",
        "ilm", "hikmah",
        "rizq", "riba", "khamr", "zakat", "sadaqah", "muamalat",
        "tawbah", "istighfar",
        "jannah", "jahannam", "qiyamah", "akhirah", "barzakh",
        "mizan", "sirat", "qadar",
        "firaun", "musa", "isa", "ibrahim", "nuh",
        "yusuf", "dawud", "sulayman", "dajjal",
        "jiran", "aurat", "huqooq", "nikah", "talaq", "wasiyah",
        "hudud", "halal", "haram", "makruh", "wajib",
        "amanah", "risalah",
        "dunya", "tawasul",
        "patience in quran", "prayer in quran", "marriage in islam",
        "women in islam", "parents in islam", "forgiveness in islam",
        "story of", "prophet in quran",
        "charity in islam", "charity in quran",
        "justice in islam", "justice in quran",
        "fasting in islam", "fasting in quran",
        "modesty in islam", "hijab in islam", "hijab in quran",
        "death in islam", "death in quran",
        "creation in islam", "creation in quran",
        "divorce in islam", "divorce in quran",
        "rights in islam", "rights in quran",
        "honesty in islam", "honesty in quran",
        "lying in islam", "lying in quran",
        "backbiting in islam", "backbiting in quran",
        "knowledge in islam", "knowledge in quran",
        "wisdom in islam", "wisdom in quran",
        "neighbors in islam", "neighbors in quran",
        "parents in islam", "parents in quran",
        "orphans in islam", "orphans in quran",
        "widows in islam", "widows in quran",
        "poor in islam", "poor in quran",
        "trade in islam", "trade in quran",
        "business in islam", "business in quran",
        "interest in islam", "interest in quran",
        "usury in islam", "usury in quran",
        "alcohol in islam", "alcohol in quran",
        "wine in islam", "wine in quran",
        "intoxicants in islam", "intoxicants in quran",
        "hellfire in islam", "hellfire in quran",
        "hell in islam", "hell in quran",
        "paradise in islam", "paradise in quran",
        "heaven in islam", "heaven in quran",
        "garden in islam", "garden in quran",
        "judgment day in islam", "judgment day in quran",
        "day of judgment in islam", "day of judgment in quran",
        "resurrection in islam", "resurrection in quran",
        "hereafter in islam", "hereafter in quran",
        "afterlife in islam", "afterlife in quran",
        "jesus in islam", "jesus in quran",
        "moses in islam", "moses in quran",
        "abraham in islam", "abraham in quran",
        "noah in islam", "noah in quran",
        "joseph in islam", "joseph in quran",
        "david in islam", "david in quran",
        "solomon in islam", "solomon in quran",
        "pharaoh in islam", "pharaoh in quran",
        "antichrist in islam", "antichrist in quran",
        "dajjal in islam", "dajjal in quran",
        "wife in islam", "wife in quran",
        "husband in islam", "husband in quran",
        "children in islam", "children in quran",
        "in islam", "in quran",
        "islamic", "allah says",
        "quran", "allah", "prophet", "according to",
    ]

    if any(trigger in message_lower for trigger in QURAN_QUERY_TRIGGERS):
        juz_match = re.search(r'\b(?:juz|para|parah)\s+(\d{1,2})\b', message_lower)
        if juz_match:
            result = rag_service._handle_juz_query(message_lower)
            if result:
                logger.info("⚡ Juz query — no LLM")
                return result

        if any(p in message_lower for p in [
            "how many words", "how many letters", "how many verses",
            "how many ayat", "word count", "letter count",
            "total words", "total letters", "how many surahs", "surahs in quran",
            "longest surah", "longest chapter", "longest surat",
            "longest verse", "longest ayah", "longest ayat", 
            "shortest verse", "shortest ayah", "shortest ayat",
            "most verses surah", "most verses chapter", "surah with most verses",
        ]):
            result = rag_service._handle_stats_query(message_lower)
            if result:
                logger.info("⚡ Stats query — no LLM")
                return result

        similar_match = re.search(
            r'similar.*?([1-9]|[1-9]\d|1[01]\d|114):([1-9]\d{0,2})'
            r'|([1-9]|[1-9]\d|1[01]\d|114):([1-9]\d{0,2}).*?similar',
            message_lower
        )
        if similar_match:
            g = similar_match.groups()
            sid = int(g[0] or g[2])
            vid = int(g[1] or g[3])
            logger.info(f"⚡ Similar ayahs {sid}:{vid} — no LLM")
            return rag_service._handle_similar_ayahs_query(sid, vid)
        elif any(p in message_lower for p in ["similar ayahs", "similar verses",
                                               "related ayahs", "similar"]):
            ctx_sid = rag_service._get_user_context(user_id).get("last_surah_id")
            ctx_vid = rag_service._get_user_context(user_id).get("last_verse_id")
            if ctx_sid and ctx_vid:
                logger.info(f"⚡ Similar ayahs from context {ctx_sid}:{ctx_vid}")
                return rag_service._handle_similar_ayahs_query(ctx_sid, ctx_vid)

    BROAD_TOPIC_TRIGGERS = [
            "verses about", "ayat about", "patience", "forgiveness", "charity",
            "prayer", "marriage", "parents", "death", "paradise", "judgment",
            "fasting", "honesty", "sabr", "tawakkul", "taqwa", "jannah", "jahannam",
            "sisters", "brothers", "rights", "inheritance", "women", "children",
            "family", "divorce", "nikah", "husband", "wife", "daughter", "son",
            "mother", "father", "relatives", "orphan", "widow", "justice",
            "business", "trade", "riba", "interest", "alcohol", "hijab",
            "modesty", "neighbors", "lying", "backbiting", "knowledge",
            "wisdom", "creation", "jesus", "musa", "dajjal", "hellfire",
            "halal", "haram", "zakat", "sadaqah", "salah", "prayer",
            "fasting", "sawm", "hajj", "umrah", "jihad", "shahada",
        ]

    if any(t in message_lower for t in BROAD_TOPIC_TRIGGERS):
        direct_result = rag_service.get_direct_answer(message) or rag_service._handle_quran_topic_query(message)
        if direct_result and "couldn't find" not in direct_result.lower():
            logger.info("⚡ Topic query — direct RAG (no LLM)")
            return direct_result

        rag_data = rag_service.get_rag_data_for_llm(message)
        if rag_data:
            logger.info("🤖 RAG data found → LLM enrichment")
            return _call_llm_with_rag(message, rag_data, user_profile)

        logger.info("🤖 No RAG data for quran query → main LLM")
        return None

    CONFIRM = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "alright", "yes please"}
    if message_lower in CONFIRM:
        ctx = (last_question + " " + context).lower()
        last_surah_name = rag_service._get_user_context(user_id).get("last_surah_name", "")
        last_surah_id   = rag_service._get_user_context(user_id).get("last_surah_id")

        if any(w in ctx for w in ["features", "learn more", "what can you do"]):
            return get_features_response()
        if any(w in ctx for w in ["salah", "prayer", "namaz"]):
            return (
                "Great! You can check accurate prayer times, set Adhan notifications, "
                "track your prayer streaks, and learn how to pray step by step. "
                "Would you like help setting up prayer notifications? 🕌"
            )
        if "quran" in ctx:
            if last_surah_name:
                return (
                    f"Great! You were reading **{last_surah_name}**. "
                    "Would you like to continue from where you left off, "
                    "or shall I show you a specific verse? 📖"
                )
            return (
                "Wonderful! The Quran module lets you read with English, "
                "Kashmiri (with Tafsir), and Urdu translations. Works offline! 📖"
            )
        
        CORRECTION_WORDS = {"wrong", "incorrect", "not correct", "that's wrong", "mistake"}
        if any(w in message_lower for w in CORRECTION_WORDS):
            last_bot_message = memory.get_last_bot_message(user_id)
            if last_bot_message:
                return (
                    "I apologize for the error. Could you please clarify what was wrong? "
                    "I want to make sure I give you accurate information. "
                    "For Quran-related questions, you can also check the Quran module "
                    "directly in the app for verified translations."
                )
        if any(w in ctx for w in ["habit", "consistent", "streak"]):
            return (
                "Excellent! The Habit Tracker helps you build consistency in Salah, "
                "Quran reading, Fasting, and Dhikr. Start with one small habit — "
                "even tracking just Fajr daily makes a huge difference! ⭐"
            )
        if last_surah_id and any(w in ctx for w in ["read", "verse", "show", "more"]):
            rag_data = rag_service.get_rag_data_for_llm(message, user_id=user_id)
            if rag_data:
                return _call_llm_with_rag(f"tell me about surah {last_surah_name}", rag_data, user_profile)

    if intent == "greeting":
        return "Assalamu alaikum! Welcome to SiratSync. How can I help you with your Islamic journey today? 🤲"

    if intent == "farewell":
        return "JazakAllah khair for using SiratSync. May Allah keep you consistent. Come back anytime! 🤲"

    if any(p in message_lower for p in ["what can you do", "help me", "how can you help"]):
        return (
            "I can help you with:\n\n"
            "📖 Reading Quran with translations\n"
            "🕌 Prayer times and Adhan notifications\n"
            "📚 Authentic Hadith collections\n"
            "📿 Duas for every situation\n"
            "⭐ Building consistent Islamic habits\n"
            "🧭 Finding Qibla direction\n"
            "👥 Connecting with the Islamic community\n\n"
            "What would you like to explore?"
        )

    if any(p in message_lower for p in ["who made you", "who created you", "who built you"]):
        return (
            "I was created by Kaiser Mohiuddin, a CS student passionate about helping "
            "Muslims through technology. He believes in using AI to make Islamic "
            "practices accessible and meaningful. 📱"
        )

    if "what is siratsync" in message_lower:
        return (
            "SiratSync is a complete Islamic lifestyle app with Quran (multiple "
            "translations), prayer times, hadith, habit tracking, community features, "
            "and more. All free, no ads! Built to help you stay consistent in your deen. 🌟"
        )

    if intent == "salah" and "time" in message_lower:
        return (
            "You can check accurate prayer times in the Prayer section. "
            "Make sure location is enabled. Would you like help setting up Adhan notifications? 🕌"
        )

    if intent == "quran" and any(w in message_lower for w in ["read", "how", "open"]):
        return (
            "Open the Quran module to read with Arabic text and translations "
            "(English, Kashmiri with Tafsir, Urdu). Adjust font size and themes "
            "for comfort. Works offline after download! 📖"
        )

    if intent == "habit_related" and any(w in message_lower for w in ["track", "how", "start"]):
        if user_profile.get("consistency") == "struggling":
            return "Start with just ONE habit — track Fajr prayer daily. Small steps build big changes. Allah loves consistency! 💪"
        return (
            "Use the Habit Tracker to log Salah, Quran, and Dhikr. Set daily goals "
            "and watch your streaks grow! Remember: small consistent deeds are most "
            "beloved to Allah. ⭐"
        )

    if intent == "dua_dhikr" and any(w in message_lower for w in ["anxiety", "stress", "worried", "sad"]):
        return (
            "Recite 'Hasbunallahu wa ni'mal wakeel' (Allah is sufficient for us). "
            "Also try 'Allahumma inni a'udhu bika minal hammi wal hazan' for anxiety relief. "
            "May Allah bring peace to your heart. 🤲"
        )

    if intent == "hadith" and "daily" in message_lower:
        return (
            "Enable Daily Hadith in Settings → Notifications. You'll receive an authentic "
            "hadith every morning from Sahih Bukhari or Muslim. 📚"
        )

    if intent == "qibla":
        return (
            "Open Qibla Finder, calibrate your compass by moving the phone in a figure-8 "
            "motion, then follow the arrow to Mecca. Works offline! 🧭"
        )

    if intent == "ramadan":
        return (
            "Enable Ramadan Mode for Suhoor/Iftar timings, special duas, and fasting "
            "reminders. May Allah bless your Ramadan! 🌙"
        )

    if "offline" in message_lower:
        return (
            "SiratSync works offline for Quran, Hadith, Duas, Qibla, and Tasbih. "
            "Download content once while online, then access anytime. Perfect for travel! 📴"
        )

    if any(p in message_lower for p in ["learn salah", "how to pray", "namaz guide"]):
        return (
            "Go to the Learn Salah module for a step-by-step guide with actions, words, "
            "and meanings. Perfect for beginners or anyone wanting to improve their prayer! 🎯"
        )

    if "community" in message_lower:
        return (
            "Join our peaceful Islamic community! Share reminders, follow others, and get "
            "inspiration. All content is moderated for safety and proper adab. 👥"
        )

    if intent == "app_features_inquiry" or "features" in message_lower:
        return get_features_response()

    return None
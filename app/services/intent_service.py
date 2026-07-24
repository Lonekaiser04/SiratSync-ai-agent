"""
Rule-based intent, sentiment, and urgency detection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict


@dataclass
class IntentResult:
    primary_intent: str
    secondary_intent: str | None
    scores: dict[str, int]
    sentiment: str
    urgency: str
    sub_intent: str
    is_question: bool

    def get(self, key: str, default=None):
        """Dict-like `.get()` for backward compatibility with call sites
        that treat the result as a plain dict (e.g. `result.get("sentiment")`)."""
        return getattr(self, key, default)

    def __getitem__(self, key: str):
        return getattr(self, key)

    def to_dict(self) -> dict:
        return asdict(self)


class IntentDetector:
    _RAW_PATTERNS: dict[str, list[str]] = {
        "greeting": [
            r"\b(assalamu alaikum|assalam|salam|wa alaikum|hello|hi|hey)\b",
            r"\b(greetings|peace be upon you|good morning|good evening)\b",
            r"\b(how are you|how do you do|nice to meet)\b",
        ],
        "struggling": [
            r"(?<!never )(?<!never)\b(miss|skip|lazy|can'?t|cannot|hard|difficult|struggl|failed)\b",
            r"\b(fajr|prayer|salah|namaz) (miss|skip|lost)\b",
            r"\b(not praying|no motivation|feel tired|burnt out|exhausted)\b",
            r"\b(low iman|weak faith|feeling down|depressed|anxious)\b",
            r"\b(procrastinate|delay|postpone)\b",
        ],
        "consistent": [
            r"\b(never miss|always pray|consistent|perfect|streak)\b",
            r"\b(achieved|completed|finished|maintained)\b",
            r"\b(proud of myself|doing great|improving)\b",
            r"\b(jazakallah|barakallah|may allah reward)\b",
        ],
        "habit_related": [
            r"\b(habit|routine|daily|track|remind|streak|goal)\b",
            r"\b(consistent|consistency|istiqamah|discipline)\b",
            r"\b(quran|dhikr|fasting|sunnah|nafl|tahajjud)\b",
            r"\b(progress|analytics|statistics|chart)\b",
        ],
        "salah": [
            r"\b(salah|prayer|namaz|salat)\b",
            r"\b(fajr|dhuhr|asr|maghrib|isha|tahajjud|witir|sunnah|nafl)\b",
            r"\b(adhan|azan|call to prayer|iqamah)\b",
            r"\b(prayer time|salah time|namaz time)\b",
            r"\b(missed prayer|qada|make up prayer)\b",
        ],
        "quran": [
            r"\b(quran|qur\'?an|koran|mushaf)\b",
            r"\b(surah|ayat|verse|juz|para|tilawat|recitation)\b",
            r"\b(translation|tafsir|meaning|kashmiri|urdu|english)\b",
            r"\b(hifz|memorize|memorization|tajweed)\b",
            r"\b(read quran|listen quran|quran offline)\b",
        ],
        "dua_dhikr": [
            r"\b(dua|supplication|invocation)\b",
            r"\b(dhikr|adhkar|remembrance|zikr)\b",
            r"\b(morning dua|evening dua|after prayer)\b",
            r"\b(tasbih|subhanallah|alhamdulillah|allahu akbar)\b",
            r"\b(protection|blessing|forgiveness)\b",
        ],
        "hadith": [
            r"\b(hadith|sunnah|prophet|muhammad|pbuh)\b",
            r"\b(bukhari|muslim|tirmidhi|abudawud|nasai|ibnmajah)\b",
            r"\b(sahih|authentic|narration|tradition)\b",
            r"\b(daily hadith|hadith reminder)\b",
        ],
        "community": [
            r"\b(community|social|feed|post|share)\b",
            r"\b(follow|follower|like|comment|interact)\b",
            r"\b(reminder|reflection|beneficial)\b",
            r"\b(moderation|report|guideline|adab)\b",
        ],
        "ramadan": [
            r"\b(ramadan|ramzan|ramadhan)\b",
            r"\b(fasting|sawm|roza|suhoor|sehri|iftar)\b",
            r"\b(taraweeh|qiyam|laylatul qadr)\b",
            r"\b(eid|fitr|zakat|sadaqah)\b",
        ],
        "learn": [
            r"\b(learn|teach|guide|step by step)\b",
            r"\b(learn salah|how to pray|namaz guide)\b",
            r"\b(shahada|shahadat|kalima|testimony of faith)\b",
            r"\b(beginner|new muslim|revert|convert)\b",
            r"\b(aurad e fatiha|aurad|fatiha)\b",
        ],
        "technical": [
            r"\b(not working|error|crash|bug|issue|problem)\b",
            r"\b(setting|configure|enable|disable)\b",
            r"\b(adhan not|qibla not|prayer time wrong)\b",
            r"\b(offline|download|sync|update)\b",
        ],
        "qibla": [
            r"\b(qibla|kibla|direction|compass)\b",
            r"\b(mecca|makkah|kaaba|haram)\b",
            r"\b(qibla direction|prayer direction)\b",
        ],
        "calendar": [
            r"\b(hijri|islamic date|hijri date)\b",
            r"\b(muharram|safar|rabi|rajab|shaban|shawwal|dhul hijjah)\b",
            r"\b(islamic month|moon phase)\b",
        ],
        "tasbih": [
            r"\b(tasbih|tasbeeh|counter|digital tasbih)\b",
            r"\b(dhikr counter|count dhikr)\b",
        ],
        "farewell": [
            r"\b(goodbye|bye|farewell|see you|take care)\b",
            r"\b(khuda hafiz|allah hafiz|ma\'?a salama)\b",
            r"\b(end conversation|that'?s all|thanks for help)\b",
        ],
        "positive_feedback": [
            r"\b(great app|awesome|fantastic|excellent|wonderful)\b",
            r"\b(thank you|thanks|jazakallah|barakallah)\b",
            r"\b(i love|i enjoy|very helpful)\b",
        ],
        "negative_feedback": [
            r"\b(bad|terrible|worst|useless|disappointed)\b",
            r"\b(not helpful|doesn'?t work|waste of time)\b",
            r"\b(angry|frustrated|annoying)\b",
        ],
    }

    # Patterns used only to set `is_question`; not a competing intent bucket.
    _QUESTION_PATTERNS = [
        r"\b(what|how|why|when|which|where|who)\b",
        r"\b(tell me|explain|describe|define|mean)\b",
        r"\b(how to|why is|what is|how do i|can you)\b",
        r"\?\s*$",
    ]

    # Intents ordered from most to least "specific" - used to break score
    # ties deterministically in favor of the more topical/actionable intent
    # rather than whichever key happened to be inserted first.
    _TIE_BREAK_PRIORITY = [
        "struggling", "consistent", "salah", "quran", "dua_dhikr", "hadith",
        "habit_related", "ramadan", "learn", "technical", "qibla", "calendar",
        "tasbih", "community", "negative_feedback", "positive_feedback",
        "farewell", "greeting",
    ]

    def __init__(self) -> None:
        self.patterns: dict[str, list[re.Pattern]] = {
            intent: [re.compile(p, re.IGNORECASE) for p in pats]
            for intent, pats in self._RAW_PATTERNS.items()
        }
        self._question_patterns = [re.compile(p, re.IGNORECASE) for p in self._QUESTION_PATTERNS]

    def detect(self, message: str) -> IntentResult:
        """Detect intent, sentiment, urgency, and sub-intent for a message."""
        if not message or not message.strip():
            return IntentResult(
                primary_intent="general",
                secondary_intent=None,
                scores={},
                sentiment="neutral",
                urgency="low",
                sub_intent="general",
                is_question=False,
            )

        message_lower = message.lower()

        scores: dict[str, int] = {intent: 0 for intent in self.patterns}
        for intent, compiled_patterns in self.patterns.items():
            for pattern in compiled_patterns:
                if pattern.search(message_lower):
                    scores[intent] += 1

        is_question = any(p.search(message_lower) for p in self._question_patterns)

        primary = self._resolve_primary_intent(scores)

        sorted_intents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        secondary = None
        for name, score in sorted_intents:
            if name != primary and score > 0:
                secondary = name
                break

        sentiment = self._determine_sentiment(scores)
        urgency = self._determine_urgency(scores)
        sub_intent = self._get_sub_intent(message_lower, primary)

        return IntentResult(
            primary_intent=primary,
            secondary_intent=secondary,
            scores=scores,
            sentiment=sentiment,
            urgency=urgency,
            sub_intent=sub_intent,
            is_question=is_question,
        )

    def _resolve_primary_intent(self, scores: dict[str, int]) -> str:
        max_score = max(scores.values(), default=0)
        if max_score == 0:
            return "general"

        tied = [intent for intent, score in scores.items() if score == max_score]
        if len(tied) == 1:
            return tied[0]

        # Deterministic tie-break: prefer the most specific intent per
        # _TIE_BREAK_PRIORITY, falling back to sorted-name order for any
        # intent not explicitly ranked (keeps behavior fully deterministic).
        for intent in self._TIE_BREAK_PRIORITY:
            if intent in tied:
                return intent
        return sorted(tied)[0]

    @staticmethod
    def _determine_sentiment(scores: dict[str, int]) -> str:
        if scores.get("positive_feedback", 0) > 0:
            return "positive"
        if scores.get("negative_feedback", 0) > 0:
            return "negative"
        if scores.get("struggling", 0) > 0:
            return "concerned"
        if scores.get("consistent", 0) > 0:
            return "encouraged"
        return "neutral"

    @staticmethod
    def _determine_urgency(scores: dict[str, int]) -> str:
        struggling = scores.get("struggling", 0)
        technical = scores.get("technical", 0)
        if struggling >= 2 or technical >= 2:
            return "high"
        if struggling == 1 or technical == 1:
            return "medium"
        return "low"

    def _get_sub_intent(self, message: str, primary_intent: str) -> str:
        """Get a more specific sub-intent for precise responses."""

        if primary_intent == "salah":
            if "time" in message or "when" in message:
                return "prayer_time_query"
            if "miss" in message or "skip" in message:
                return "missed_prayer"
            if "how" in message or "learn" in message:
                return "learn_prayer"
            if "adhan" in message or "azan" in message:
                return "adhan_notification"
            return "general_salah"

        if primary_intent == "quran":
            if "read" in message or "recite" in message:
                return "reading_quran"
            if "translation" in message or "meaning" in message:
                return "quran_translation"
            if "listen" in message or "recitation" in message:
                return "quran_recitation"
            if "offline" in message:
                return "quran_offline"
            return "general_quran"

        if primary_intent == "dua_dhikr":
            if "morning" in message:
                return "morning_adhkar"
            if "evening" in message:
                return "evening_adhkar"
            if "tasbih" in message or "counter" in message:
                return "tasbih_counter"
            if "anxiety" in message or "stress" in message:
                return "dua_for_anxiety"
            if "study" in message or "focus" in message:
                return "dua_for_study"
            return "general_dua"

        if primary_intent == "hadith":
            if "daily" in message:
                return "daily_hadith"
            if "bukhari" in message:
                return "bukhari_hadith"
            if "muslim" in message:
                return "muslim_hadith"
            if "search" in message or "find" in message:
                return "search_hadith"
            return "general_hadith"

        if primary_intent == "habit_related":
            if "streak" in message:
                return "streak_tracking"
            if "track" in message or "log" in message:
                return "habit_logging"
            if "analytics" in message or "progress" in message:
                return "habit_analytics"
            return "general_habit"

        if primary_intent == "ramadan":
            if "suhoor" in message or "sehri" in message:
                return "suhoor_time"
            if "iftar" in message:
                return "iftar_time"
            if "dua" in message:
                return "ramadan_dua"
            return "general_ramadan"

        if primary_intent == "learn":
            if "salah" in message or "pray" in message:
                return "learn_salah"
            if "shahada" in message or "kalima" in message:
                return "learn_shahadat"
            if "aurad" in message:
                return "aurad_e_fatiha"
            return "general_learning"

        if primary_intent == "community":
            if "share" in message or "post" in message:
                return "sharing_content"
            if "follow" in message:
                return "following_users"
            if "report" in message or "moderate" in message:
                return "report_content"
            return "general_community"

        if primary_intent == "technical":
            if "not working" in message or "error" in message:
                return "app_issue"
            if "how to" in message:
                return "setup_guide"
            if "offline" in message:
                return "offline_access"
            return "general_technical"

        if primary_intent == "struggling":
            if "motivation" in message:
                return "low_motivation"
            if "miss" in message:
                return "missed_worship"
            if "tired" in message or "exhausted" in message:
                return "burnout"
            return "general_struggle"

        return "general"

    def get_response_template(self, intent: str, sub_intent: str | None = None) -> str:
        """Get a response template based on detected intent (fallback path
        used only when the richer quick-reply / LLM pipeline doesn't apply)."""

        templates = {
            "greeting": "Assalamu alaikum! Welcome to SiratSync. How can I help you with your Islamic journey today? 🤝",
            "struggling": "Don't be hard on yourself, dear brother/sister. The fact that you care shows your iman is alive. Start small - even one prayer on time is a victory. I believe in you! 💪",
            "consistent": "MashaAllah! Your consistency is inspiring. Remember, the most beloved deeds to Allah are those done regularly, even if small. Keep going! 🌟",
            "salah": "🕌 I can help with prayer times, Adhan notifications, missed prayers, or learning Salah. What specifically would you like to know?",
            "quran": "📖 The Quran module has Arabic text with English, Kashmiri (with Tafsir), and Urdu translations. Would you like help with reading, recitation, or finding a specific surah?",
            "dua_dhikr": "📿 I can share authentic duas for various situations - morning/evening adhkar, before eating, entering mosque, anxiety, study focus, and more. What do you need?",
            "hadith": "📚 SiratSync includes Sahih al-Bukhari and Sahih Muslim. You can browse by book, search, bookmark, and get daily hadith reminders. How can I help?",
            "habit_related": "⭐ The Habit Tracker helps you build consistency in Salah, Quran, Fasting, and Dhikr. Set daily goals and watch your streaks grow!",
            "ramadan": "🌙 Ramadan Mode includes Suhoor/Iftar timings, special duas, fasting reminders, and prayer countdown. May Allah bless your Ramadan!",
            "learn": "🎯 SiratSync has 'Learn Salah' step-by-step guide and Shahadat in 14 languages. What would you like to learn today?",
            "community": "👥 The Community is a peaceful Islamic space to share reminders, follow others, and build a personalized feed. All content is moderated for safety.",
            "technical": "🔧 I'll help you troubleshoot. What issue are you experiencing with SiratSync?",
            "qibla": "🧭 Use Qibla Finder - calibrate your compass and follow the arrow to Mecca. Works offline after calibration.",
            "calendar": "📅 The Islamic Calendar shows today's Hijri date and Islamic months. Want to know a specific date?",
            "tasbih": "📿 The digital Tasbih Counter helps you track dhikr. Count Subhanallah, Alhamdulillah, Allahu Akbar, or set custom goals.",
            "farewell": "JazakAllah khair for using SiratSync. May Allah keep us all consistent. Come back anytime! 🤝",
            "positive_feedback": "Alhamdulillah! Thank you for your kind words. May Allah reward you. Keep striving! 🤝",
            "negative_feedback": "I'm sorry you're having a bad experience. Please share the issue so we can improve. Email lonekaiser04@gmail.com for direct support.",
            "general": "I'm here to help with SiratSync features, Islamic guidance, and daily worship tips. Ask me about Salah, Quran, Duas, Hadith, Habit tracking, or the Community! 📱",
        }

        if sub_intent:
            sub_templates = {
                "missed_prayer": "Don't worry - make up missed prayers as soon as you remember. Allah loves those who repent and return. Start with one prayer at a time.",
                "low_motivation": "I understand. Even the Sahaba (companions) had ups and downs. Make sincere dua and start with just 2 minutes of Quran daily. You can do this!",
                "quran_translation": "SiratSync offers English, Kashmiri (with Tafsir), and Urdu translations. Go to Quran -> Settings -> Select Translation to change your preference.",
                "dua_for_anxiety": "Recite 'Hasbunallahu wa ni'mal wakeel' - Allah is sufficient for us, and He is the best disposer of affairs. May Allah bring peace to your heart.",
                "daily_hadith": "Enable Daily Hadith in Settings -> Notifications. You'll receive authentic hadith every morning to start your day with inspiration!",
                "streak_tracking": "Your streak shows consistency, not perfection. Even 1 prayer tracked is better than none. Keep building, day by day!",
            }
            if sub_intent in sub_templates:
                return sub_templates[sub_intent]

        return templates.get(intent, templates["general"])


# Singleton instance used across the application.
intent_detector = IntentDetector()

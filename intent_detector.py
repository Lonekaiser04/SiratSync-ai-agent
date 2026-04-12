import re

class IntentDetector:
    def __init__(self):
        self.patterns = {
            # Greetings & Islamic greetings
            "greeting": [
                r"\b(assalamu alaikum|assalam|salam|wa alaikum|hello|hi|hey)\b",
                r"\b(greetings|peace be upon you|good morning|good evening)\b",
                r"\b(how are you|how do you do|nice to meet)\b"
            ],
            
            # Struggling with worship
            "struggling": [
                r"\b(miss|skip|lazy|can'?t|cannot|hard|difficult|struggl|failed)\b",
                r"\b(fajr|prayer|salah|namaz) (miss|skip|lost)\b",
                r"\b(not praying|no motivation|feel tired|burnt out|exhausted)\b",
                r"\b(low iman|weak faith|feeling down|depressed|anxious)\b",
                r"\b(procrastinate|delay|postpone)\b"
            ],
            
            # Consistent & positive
            "consistent": [
                r"\b(never miss|always pray|consistent|perfect|streak)\b",
                r"\b(achieved|completed|finished|maintained)\b",
                r"\b(proud of myself|doing great|improving)\b",
                r"\b(jazakallah|barakallah|may allah reward)\b"
            ],
            
            # Questions
            "question": [
                r"\b(what|how|why|when|which|where|who)\b",
                r"\b(tell me|explain|describe|define|mean)\b",
                r"\b(how to|why is|what is|how do i|can you)\b"
            ],
            
            # Habit tracking related
            "habit_related": [
                r"\b(habit|routine|daily|track|remind|streak|goal)\b",
                r"\b(consistent|consistency|istiqamah|discipline)\b",
                r"\b(quran|dhikr|fasting|sunnah|nafl|tahajjud)\b",
                r"\b(progress|analytics|statistics|chart)\b"
            ],
            
            # Salah/Prayer specific
            "salah": [
                r"\b(salah|prayer|namaz|salat)\b",
                r"\b(fajr|dhuhr|asr|maghrib|isha|tahajjud|witir|sunnah|nafl)\b",
                r"\b(adhan|azan|call to prayer|iqamah)\b",
                r"\b(prayer time|salah time|namaz time)\b",
                r"\b(missed prayer|qada|make up prayer)\b"
            ],
            
            # Quran specific
            "quran": [
                r"\b(quran|qur\'?an|koran|mushaf)\b",
                r"\b(surah|ayat|verse|juz|para|tilawat|recitation)\b",
                r"\b(translation|tafsir|meaning|kashmiri|urdu|english)\b",
                r"\b(hifz|memorize|memorization|tajweed)\b",
                r"\b(read quran|listen quran|quran offline)\b"
            ],
            
            # Dua & Dhikr specific
            "dua_dhikr": [
                r"\b(dua|supplication|prayer|invocation)\b",
                r"\b(dhikr|adhkar|remembrance|zikr)\b",
                r"\b(morning dua|evening dua|after prayer)\b",
                r"\b(tasbih|subhanallah|alhamdulillah|allahu akbar)\b",
                r"\b(protection|blessing|forgiveness)\b"
            ],
            
            # Hadith specific
            "hadith": [
                r"\b(hadith|sunnah|prophet|muhammad|pbuh)\b",
                r"\b(bukhari|muslim|tirmidhi|abudawud|nasai|ibnmajah)\b",
                r"\b(sahih|authentic|narration|tradition)\b",
                r"\b(daily hadith|hadith reminder)\b"
            ],
            
            # Community features
            "community": [
                r"\b(community|social|feed|post|share)\b",
                r"\b(follow|follower|like|comment|interact)\b",
                r"\b(reminder|reflection|beneficial)\b",
                r"\b(moderation|report|guideline|adab)\b"
            ],
            
            # Ramadan specific
            "ramadan": [
                r"\b(ramadan|ramzan|ramadhan)\b",
                r"\b(fasting|sawm|roza|suhoor|sehri|iftar)\b",
                r"\b(taraweeh|qiyam|laylatul qadr)\b",
                r"\b(eid|fitr|zakat|sadaqah)\b"
            ],
            
            # Learn & Education
            "learn": [
                r"\b(learn|teach|guide|how to|step by step)\b",
                r"\b(learn salah|how to pray|namaz guide)\b",
                r"\b(shahada|shahadat|kalima|testimony of faith)\b",
                r"\b(beginner|new muslim|revert|convert)\b",
                r"\b(aurad e fatiha|aurad|fatiha)\b"
            ],
            
            # Technical/App help
            "technical": [
                r"\b(not working|error|crash|bug|issue|problem)\b",
                r"\b(how to|setting|configure|enable|disable)\b",
                r"\b(adhan not|qibla not|prayer time wrong)\b",
                r"\b(offline|download|sync|update)\b"
            ],
            
            # Qibla specific
            "qibla": [
                r"\b(qibla|kibla|direction|compass)\b",
                r"\b(mecca|makkah|kaaba|haram)\b",
                r"\b(qibla direction|prayer direction)\b"
            ],
            
            # Islamic Calendar
            "calendar": [
                r"\b(hijri|islamic date|hijri date)\b",
                r"\b(muharram|safar|rabi|rajab|shaban|shawwal|dhul hijjah)\b",
                r"\b(islamic month|moon phase)\b"
            ],
            
            # Tasbih Counter
            "tasbih": [
                r"\b(tasbih|tasbeeh|counter|digital tasbih)\b",
                r"\b(dhikr counter|count dhikr)\b"
            ],
            
            # Farewell/Goodbye
            "farewell": [
                r"\b(goodbye|bye|farewell|see you|take care)\b",
                r"\b(khuda hafiz|allah hafiz|ma\'?a salama)\b",
                r"\b(end conversation|that'?s all|thanks for help)\b"
            ],
            
            # Positive feedback
            "positive_feedback": [
                r"\b(great app|awesome|fantastic|excellent|wonderful)\b",
                r"\b(thank you|thanks|jazakallah|barakallah)\b",
                r"\b(i love|i enjoy|very helpful)\b"
            ],
            
            # Negative feedback
            "negative_feedback": [
                r"\b(bad|terrible|worst|useless|disappointed)\b",
                r"\b(not helpful|doesn'?t work|waste of time)\b",
                r"\b(angry|frustrated|annoying)\b"
            ]
        }
    
    def detect(self, message: str) -> dict:
        """Detect intent from user message"""
        message_lower = message.lower()
        
        scores = {
            "greeting": 0,
            "struggling": 0,
            "consistent": 0,
            "question": 0,
            "habit_related": 0,
            "salah": 0,
            "quran": 0,
            "dua_dhikr": 0,
            "hadith": 0,
            "community": 0,
            "ramadan": 0,
            "learn": 0,
            "technical": 0,
            "qibla": 0,
            "calendar": 0,
            "tasbih": 0,
            "farewell": 0,
            "positive_feedback": 0,
            "negative_feedback": 0
        }
        
        for intent, patterns in self.patterns.items():
            for pattern in patterns:
                if re.search(pattern, message_lower, re.IGNORECASE):
                    scores[intent] += 1
        
        # Determine primary intent (highest score)
        primary = max(scores, key=scores.get)
        if scores[primary] == 0:
            primary = "general"
        
        # Determine secondary intent for context
        sorted_intents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        secondary = sorted_intents[1][0] if len(sorted_intents) > 1 and sorted_intents[1][1] > 0 else None
        
        # Determine user sentiment
        sentiment = "neutral"
        if scores["positive_feedback"] > 0:
            sentiment = "positive"
        elif scores["negative_feedback"] > 0:
            sentiment = "negative"
        elif scores["struggling"] > 0:
            sentiment = "concerned"
        elif scores["consistent"] > 0:
            sentiment = "encouraged"
        
        # Determine urgency (for struggling/technical issues)
        urgency = "low"
        if scores["struggling"] >= 2 or scores["technical"] >= 2:
            urgency = "high"
        elif scores["struggling"] == 1 or scores["technical"] == 1:
            urgency = "medium"
        
        # Get specific sub-intent for better response
        sub_intent = self._get_sub_intent(message_lower, primary)
        
        return {
            "primary_intent": primary,
            "secondary_intent": secondary,
            "scores": scores,
            "sentiment": sentiment,
            "urgency": urgency,
            "sub_intent": sub_intent,
            "is_question": scores["question"] > 0
        }
    
    def _get_sub_intent(self, message: str, primary_intent: str) -> str:
        """Get more specific sub-intent for precise responses"""
        
        if primary_intent == "salah":
            if "time" in message or "when" in message:
                return "prayer_time_query"
            elif "miss" in message or "skip" in message:
                return "missed_prayer"
            elif "how" in message or "learn" in message:
                return "learn_prayer"
            elif "adhan" in message or "azan" in message:
                return "adhan_notification"
            return "general_salah"
        
        elif primary_intent == "quran":
            if "read" in message or "recite" in message:
                return "reading_quran"
            elif "translation" in message or "meaning" in message:
                return "quran_translation"
            elif "listen" in message or "recitation" in message:
                return "quran_recitation"
            elif "offline" in message:
                return "quran_offline"
            return "general_quran"
        
        elif primary_intent == "dua_dhikr":
            if "morning" in message:
                return "morning_adhkar"
            elif "evening" in message:
                return "evening_adhkar"
            elif "tasbih" in message or "counter" in message:
                return "tasbih_counter"
            elif "anxiety" in message or "stress" in message:
                return "dua_for_anxiety"
            elif "study" in message or "focus" in message:
                return "dua_for_study"
            return "general_dua"
        
        elif primary_intent == "hadith":
            if "daily" in message:
                return "daily_hadith"
            elif "bukhari" in message:
                return "bukhari_hadith"
            elif "muslim" in message:
                return "muslim_hadith"
            elif "search" in message or "find" in message:
                return "search_hadith"
            return "general_hadith"
        
        elif primary_intent == "habit_related":
            if "streak" in message:
                return "streak_tracking"
            elif "track" in message or "log" in message:
                return "habit_logging"
            elif "analytics" in message or "progress" in message:
                return "habit_analytics"
            return "general_habit"
        
        elif primary_intent == "ramadan":
            if "suhoor" in message or "sehri" in message:
                return "suhoor_time"
            elif "iftar" in message:
                return "iftar_time"
            elif "dua" in message:
                return "ramadan_dua"
            return "general_ramadan"
        
        elif primary_intent == "learn":
            if "salah" in message or "pray" in message:
                return "learn_salah"
            elif "shahada" in message or "kalima" in message:
                return "learn_shahadat"
            elif "aurad" in message:
                return "aurad_e_fatiha"
            return "general_learning"
        
        elif primary_intent == "community":
            if "share" in message or "post" in message:
                return "sharing_content"
            elif "follow" in message:
                return "following_users"
            elif "report" in message or "moderate" in message:
                return "report_content"
            return "general_community"
        
        elif primary_intent == "technical":
            if "not working" in message or "error" in message:
                return "app_issue"
            elif "how to" in message:
                return "setup_guide"
            elif "offline" in message:
                return "offline_access"
            return "general_technical"
        
        elif primary_intent == "struggling":
            if "motivation" in message:
                return "low_motivation"
            elif "miss" in message:
                return "missed_worship"
            elif "tired" in message or "exhausted" in message:
                return "burnout"
            return "general_struggle"
        
        return "general"
    
    def get_response_template(self, intent: str, sub_intent: str = None) -> str:
        """Get a response template based on detected intent"""
        
        templates = {
            "greeting": "Assalamu alaikum! Welcome to SiratSync. How can I help you with your Islamic journey today? 🤲",
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
            "farewell": "JazakAllah khair for using SiratSync. May Allah keep us all consistent. Come back anytime! 🤲",
            "positive_feedback": "Alhamdulillah! Thank you for your kind words. May Allah reward you. Keep striving! 🤲",
            "negative_feedback": "I'm sorry you're having a bad experience. Please share the issue so we can improve. Email lonekaiser04@gmail.com for direct support.",
            "general": "I'm here to help with SiratSync features, Islamic guidance, and daily worship tips. Ask me about Salah, Quran, Duas, Hadith, Habit tracking, or the Community! 📱"
        }
        
        # Sub-intent specific templates
        if sub_intent:
            sub_templates = {
                "missed_prayer": "Don't worry - make up missed prayers as soon as you remember. Allah loves those who repent and return. Start with one prayer at a time. 🤲",
                "low_motivation": "I understand. Even the Sahaba (companions) had ups and downs. Make sincere dua and start with just 2 minutes of Quran daily. You can do this! 💪",
                "quran_translation": "SiratSync offers English, Kashmiri (with Tafsir), and Urdu translations. Go to Quran → Settings → Select Translation to change your preference.",
                "dua_for_anxiety": "Recite 'Hasbunallahu wa ni'mal wakeel' - Allah is sufficient for us, and He is the best disposer of affairs. May Allah bring peace to your heart. 🤲",
                "daily_hadith": "Enable Daily Hadith in Settings → Notifications. You'll receive authentic hadith every morning to start your day with inspiration!",
                "streak_tracking": "Your streak shows consistency, not perfection. Even 1 prayer tracked is better than none. Keep building, day by day! 📈"
            }
            
            if sub_intent in sub_templates:
                return sub_templates[sub_intent]
        
        return templates.get(intent, templates["general"])
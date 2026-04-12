# actions.py
from typing import Dict, List, Optional
from datetime import datetime

def suggest_actions(intent: str, user_profile: dict, sub_intent: str = None, sentiment: str = "neutral") -> dict:
    """Return actionable suggestions based on intent, user profile, and context"""
    
    actions = {
        "reminders": [],
        "habits": [],
        "duas": [],
        "resources": [],
        "encouragement": "",
        "quick_actions": []
    }
    
    # Get user consistency level
    consistency = user_profile.get("consistency", "unknown")
    struggles = user_profile.get("struggles", [])
    
    # Struggling intent - provide gentle, small steps
    if intent == "struggling":
        actions["encouragement"] = "💪 Start EXTREMELY small. Even 1 minute counts. Allah loves consistency, not perfection."
        
        # Low motivation / struggling with prayers
        if sub_intent == "low_motivation" or "prayer" in str(struggles).lower():
            actions["reminders"].append({
                "type": "prayer",
                "title": "Start with ONE prayer",
                "time": "Choose any prayer you can commit to",
                "priority": "high"
            })
            actions["habits"].append({
                "title": "The 1-Minute Rule",
                "description": "Just pray Fajr on time today. Nothing else. That's your only goal.",
                "difficulty": "easy",
                "estimated_minutes": 5
            })
            actions["duas"].append({
                "situation": "When feeling lazy for prayer",
                "dua": "Allahumma inni as'aluka quwwata 'ala ta'atika",
                "meaning": "O Allah, I ask You for strength to obey You",
                "transliteration": "Allahumma inni as'aluka quwwata 'ala ta'atika"
            })
        
        # Struggling with Quran
        elif "quran" in str(struggles).lower() or sub_intent == "quran_struggle":
            actions["habits"].append({
                "title": "1 Ayah Daily",
                "description": "Read just ONE ayah with translation every day. That's it.",
                "difficulty": "easy",
                "estimated_minutes": 2
            })
            actions["quick_actions"].append({
                "action": "open_quran",
                "label": "📖 Open Quran",
                "surah": "Al-Fatiha"
            })
        
        # General struggling
        else:
            actions["habits"].append({
                "title": "The 2-Minute Dhikr",
                "description": "Say 'SubhanAllah' 33 times. Takes 2 minutes. Build from there.",
                "difficulty": "easy",
                "estimated_minutes": 2
            })
            actions["duas"].append({
                "situation": "When feeling overwhelmed",
                "dua": "Hasbunallahu wa ni'mal wakeel",
                "meaning": "Allah is sufficient for us, and He is the best disposer of affairs"
            })
        
        # Morning/evening reminder
        current_hour = datetime.now().hour
        if current_hour < 12:
            actions["reminders"].append({
                "type": "adhkar",
                "title": "Morning Adhkar",
                "time": "After Fajr (within 15 min)",
                "description": "Protects you until evening"
            })
        elif current_hour > 18:
            actions["reminders"].append({
                "type": "adhkar",
                "title": "Evening Adhkar",
                "time": "Before Maghrib",
                "description": "Protects you until morning"
            })
    
    # Consistent intent - encourage growth
    elif intent == "consistent":
        actions["encouragement"] = "🌟 MashaAllah! Your consistency is beautiful. Ready to level up?"
        
        # Suggest adding one more habit based on user's topics
        topics = user_profile.get("topics", [])
        
        if "quran" in topics:
            actions["habits"].append({
                "title": "Add Translation Reading",
                "description": "Read the meaning of what you recite daily. Deepens khushu.",
                "difficulty": "medium",
                "estimated_minutes": 5
            })
        elif "salah" in topics:
            actions["habits"].append({
                "title": "Add Sunnah Prayers",
                "description": "Add 2 rak'ah Sunnah before Fajr. Immense reward!",
                "difficulty": "medium",
                "estimated_minutes": 5
            })
        elif "dua_dhikr" in topics:
            actions["habits"].append({
                "title": "Learn New Dua Weekly",
                "description": "Memorize one new authentic dua each week.",
                "difficulty": "easy",
                "estimated_minutes": 3
            })
        else:
            actions["habits"].append({
                "title": "Maintain Streak +1",
                "description": "You're doing great! Keep your current streak alive.",
                "difficulty": "easy"
            })
        
        actions["quick_actions"].append({
            "action": "share_streak",
            "label": "🎉 Share Your Streak in Community"
        })
    
    # Greeting / New user
    elif intent == "greeting":
        actions["encouragement"] = "🤲 Welcome to SiratSync! Let's start your beautiful journey."
        
        actions["habits"].append({
            "title": "Morning Routine Setup",
            "description": "Wake up → Fajr → Morning Adhkar → 5 min Quran",
            "difficulty": "easy"
        })
        
        actions["quick_actions"].extend([
            {"action": "set_prayer_reminders", "label": "🕌 Enable Prayer Reminders"},
            {"action": "set_daily_hadith", "label": "📚 Get Daily Hadith"},
            {"action": "explore_quran", "label": "📖 Explore Quran Module"}
        ])
        
        actions["duas"].append({
            "situation": "Starting the app",
            "dua": "Allahumma inni as'aluka 'ilman naafi'an",
            "meaning": "O Allah, I ask You for beneficial knowledge"
        })
    
    # Salah/Prayer intent
    elif intent == "salah":
        if sub_intent == "missed_prayer":
            actions["habits"].append({
                "title": "Qada (Make-up) Tracker",
                "description": "Make up missed prayers gradually. Start with 1 qada per day.",
                "difficulty": "medium"
            })
            actions["quick_actions"].append({
                "action": "track_missed_prayer",
                "label": "📝 Log Missed Prayer"
            })
        
        elif sub_intent == "learn_prayer":
            actions["resources"].append({
                "title": "Learn Salah Guide",
                "type": "module",
                "location": "App → Learn Salah",
                "description": "Step-by-step with actions, words, and meanings"
            })
            actions["quick_actions"].append({
                "action": "open_learn_salah",
                "label": "🎯 Open Learn Salah Module"
            })
        
        else:
            actions["reminders"].append({
                "type": "prayer",
                "title": "Prayer Times",
                "time": "Check app for accurate timings",
                "description": "Enable Adhan notifications"
            })
            actions["quick_actions"].append({
                "action": "check_prayer_times",
                "label": "🕌 Check Today's Prayer Times"
            })
    
    # Quran intent
    elif intent == "quran":
        actions["habits"].append({
            "title": "Daily Quran Goal",
            "description": "Start with 1 page (about 2 minutes)",
            "target": "1 page/day",
            "difficulty": "easy"
        })
        
        actions["quick_actions"].extend([
            {"action": "open_quran", "label": "📖 Open Quran"},
            {"action": "set_quran_goal", "label": "🎯 Set Daily Quran Goal"}
        ])
        
        actions["resources"].append({
            "title": "Quran Translations",
            "type": "feature",
            "available": ["English", "Kashmiri + Tafsir", "Urdu"],
            "description": "Change in Quran → Settings"
        })
    
    # Dua & Dhikr intent
    elif intent == "dua_dhikr":
        if sub_intent == "morning_adhkar":
            actions["reminders"].append({
                "type": "adhkar",
                "title": "Morning Adhkar Reminder",
                "time": "After Fajr (Sunrise + 15 min)"
            })
            actions["quick_actions"].append({
                "action": "open_morning_adhkar",
                "label": "🌅 Open Morning Adhkar"
            })
        
        elif sub_intent == "evening_adhkar":
            actions["reminders"].append({
                "type": "adhkar",
                "title": "Evening Adhkar Reminder",
                "time": "After Asr"
            })
            actions["quick_actions"].append({
                "action": "open_evening_adhkar",
                "label": "🌙 Open Evening Adhkar"
            })
        
        elif sub_intent == "dua_for_anxiety":
            actions["duas"].append({
                "situation": "Anxiety & Stress",
                "dua": "Allahumma inni a'udhu bika minal hammi wal hazan",
                "meaning": "O Allah, I seek refuge in You from anxiety and sorrow",
                "frequency": "Recite daily, especially after Fajr"
            })
        
        else:
            actions["quick_actions"].append({
                "action": "open_duas",
                "label": "📿 Browse Duas by Category"
            })
    
    # Hadith intent
    elif intent == "hadith":
        actions["reminders"].append({
            "type": "hadith",
            "title": "Daily Hadith",
            "time": "Morning (8:00 AM)",
            "description": "Start day with prophetic guidance"
        })
        
        actions["quick_actions"].extend([
            {"action": "open_hadith", "label": "📚 Browse Hadith"},
            {"action": "enable_daily_hadith", "label": "🔔 Enable Daily Hadith"}
        ])
        
        actions["resources"].append({
            "title": "Hadith Collections",
            "available": ["Sahih al-Bukhari", "Sahih Muslim"],
            "coming_soon": ["Sunan Abu Dawud", "Jami at-Tirmidhi"]
        })
    
    # Habit tracking intent
    elif intent == "habit_related":
        if consistency == "struggling":
            actions["habits"].append({
                "title": "Start with ONE Habit",
                "description": "Just track Fajr for 7 days. Nothing else.",
                "tracking_period": "7 days"
            })
        elif consistency == "high":
            actions["habits"].append({
                "title": "Challenge: 30-Day Streak",
                "description": "Maintain all 5 prayers for 30 days",
                "reward": "Certificate + Community Shoutout"
            })
        else:
            actions["habits"].append({
                "title": "Add 2nd Habit",
                "description": "Track Quran reading alongside prayers",
                "estimated_minutes": 5
            })
        
        actions["quick_actions"].append({
            "action": "open_habit_tracker",
            "label": "⭐ Open Habit Tracker"
        })
    
    # Ramadan intent
    elif intent == "ramadan":
        actions["reminders"].extend([
            {"type": "suhoor", "title": "Suhoor Reminder", "time": "1 hour before Fajr"},
            {"type": "iftar", "title": "Iftar Reminder", "time": "At Maghrib"},
            {"type": "taraweeh", "title": "Taraweeh Prayer", "time": "After Isha"}
        ])
        
        actions["duas"].append({
            "situation": "Breaking fast (Iftar)",
            "dua": "Allahumma inni laka sumtu wa bika aamantu wa 'ala rizqika aftartu",
            "meaning": "O Allah, I fasted for You, believed in You, and break my fast with Your provision"
        })
        
        actions["quick_actions"].append({
            "action": "enable_ramadan_mode",
            "label": "🌙 Enable Ramadan Mode"
        })
    
    # Learn intent
    elif intent == "learn":
        if sub_intent == "learn_salah":
            actions["resources"].append({
                "title": "Complete Salah Guide",
                "type": "interactive_module",
                "location": "App → Learn Salah",
                "includes": ["Steps", "Words", "Meanings", "Common mistakes"]
            })
            actions["quick_actions"].append({
                "action": "open_learn_salah",
                "label": "🕌 Start Learning Salah"
            })
        
        elif sub_intent == "learn_shahadat":
            actions["resources"].append({
                "title": "Shahadat in 14 Languages",
                "type": "module",
                "location": "App → Shahadat",
                "languages": ["English", "Urdu", "Hindi", "Arabic", "Malay", "+9 more"]
            })
            actions["quick_actions"].append({
                "action": "open_shahadat",
                "label": "☪️ Read Shahadat"
            })
        
        else:
            actions["quick_actions"].extend([
                {"action": "open_learn_salah", "label": "🎯 Learn Salah"},
                {"action": "open_shahadat", "label": "☪️ Shahadat"},
                {"action": "open_aurad", "label": "📿 Aurad-e-Fatiha"}
            ])
    
    # Community intent
    elif intent == "community":
        actions["quick_actions"].extend([
            {"action": "open_community", "label": "👥 Browse Community Feed"},
            {"action": "share_reminder", "label": "📝 Share Islamic Reminder"},
            {"action": "find_accountability", "label": "🤝 Find Accountability Partner"}
        ])
        
        actions["reminders"].append({
            "type": "community",
            "title": "Daily Reminder",
            "description": "Post one beneficial reminder daily to earn blessings"
        })
    
    # Qibla intent
    elif intent == "qibla":
        actions["quick_actions"].append({
            "action": "open_qibla_finder",
            "label": "🧭 Find Qibla Direction"
        })
        
        actions["resources"].append({
            "title": "Qibla Tips",
            "tips": [
                "Calibrate compass by moving phone in figure-8",
                "Keep away from magnetic objects",
                "Works offline after calibration"
            ]
        })
    
    # Tasbih intent
    elif intent == "tasbih":
        actions["quick_actions"].append({
            "action": "open_tasbih",
            "label": "📿 Open Tasbih Counter"
        })
        
        actions["habits"].append({
            "title": "Daily Tasbih Goal",
            "description": "Say 'SubhanAllah' 100x daily (takes 3 minutes)",
            "target": "100/day"
        })
    
    # Technical intent - provide troubleshooting
    elif intent == "technical":
        actions["quick_actions"].append({
            "action": "check_settings",
            "label": "⚙️ Check App Settings"
        })
        
        actions["resources"].append({
            "title": "Quick Fixes",
            "fixes": [
                "Enable location for prayer times",
                "Check notification permissions",
                "Download Quran for offline use",
                "Calibrate compass for Qibla"
            ]
        })
    
    # Farewell
    elif intent == "farewell":
        actions["encouragement"] = "🤲 May Allah keep you steadfast. Come back anytime for support!"
        actions["duas"].append({
            "situation": "Leaving the app",
            "dua": "Allahumma inni as'aluka thabata 'ala deen",
            "meaning": "O Allah, I ask You for steadfastness upon the religion"
        })
    
    # Positive feedback
    elif intent == "positive_feedback":
        actions["encouragement"] = "Alhamdulillah! Your kind words mean a lot. Please consider rating SiratSync to help others find it. 🌟"
        actions["quick_actions"].append({
            "action": "rate_app",
            "label": "⭐ Rate SiratSync 5 Stars"
        })
    
    # Negative feedback
    elif intent == "negative_feedback":
        actions["encouragement"] = "I'm sorry you're having issues. Please email lonekaiser04@gmail.com for direct support. We take feedback seriously. 📧"
        actions["quick_actions"].append({
            "action": "contact_support",
            "label": "📧 Contact Developer"
        })
    
    # Default / General
    else:
        actions["quick_actions"] = [
            {"action": "check_prayer_times", "label": "🕌 Prayer Times"},
            {"action": "open_quran", "label": "📖 Read Quran"},
            {"action": "open_habit_tracker", "label": "⭐ Track Habits"},
            {"action": "open_community", "label": "👥 Community"}
        ]
    
    # Limit number of suggestions for better UX
    actions["reminders"] = actions["reminders"][:3]
    actions["habits"] = actions["habits"][:2]
    actions["duas"] = actions["duas"][:2]
    actions["quick_actions"] = actions["quick_actions"][:4]
    
    return actions


def get_motivational_quote(consistency_level: str = "unknown") -> str:
    """Return an Islamic motivational quote based on user's consistency"""
    
    quotes = {
        "struggling": [
            "💫 'The most beloved deeds to Allah are those done consistently, even if small.' - Sahih Bukhari",
            "🌱 'Do not despair of the mercy of Allah.' - Quran 39:53",
            "🕯️ 'Every son of Adam sins, and the best of sinners are those who repent.' - Tirmidhi"
        ],
        "medium": [
            "📈 'Whoever treads a path in search of knowledge, Allah makes the path to Jannah easy for them.' - Muslim",
            "🌟 'The strong believer is better and more beloved to Allah than the weak believer, but there is good in both.' - Muslim",
            "💪 'Take on only as much as you can do of good deeds, for the best of deeds is that which is done consistently, even if it is little.' - Ibn Majah"
        ],
        "high": [
            "🏆 'The example of the one who remembers Allah and the one who does not is like the example of the living and the dead.' - Bukhari",
            "🎯 'Verily, in the remembrance of Allah do hearts find rest.' - Quran 13:28",
            "⭐ 'Shall I not tell you of the best of your deeds, the purest in the sight of your Lord, which raises your rank the highest?' (Dhikr) - Tirmidhi"
        ],
        "unknown": [
            "🌟 'So verily, with hardship comes ease.' - Quran 94:5",
            "🌙 'The best among you are those who learn the Quran and teach it.' - Bukhari",
            "🕌 'Prayer is the pillar of the religion.' - Tirmidhi"
        ]
    }
    
    import random
    key = consistency_level if consistency_level in quotes else "unknown"
    return random.choice(quotes[key])


def get_quick_reply_suggestions(intent: str, sub_intent: str = None) -> List[str]:
    """Get quick reply buttons based on intent"""
    
    suggestions = {
        "greeting": ["📖 Quran", "🕌 Prayer Times", "⭐ Habits", "❓ Help"],
        "salah": ["🕒 Show Prayer Times", "🔔 Set Adhan", "📝 Missed Prayer", "🎯 Learn Salah"],
        "quran": ["📖 Open Quran", "🌙 Read Surah Al-Kahf", "📚 Translations", "🎯 Set Goal"],
        "dua_dhikr": ["🌅 Morning Adhkar", "🌙 Evening Adhkar", "😌 Dua for Anxiety", "📿 Tasbih"],
        "hadith": ["📚 Daily Hadith", "🔍 Search Hadith", "⭐ Bukhari", "⭐ Muslim"],
        "habit_related": ["⭐ Track Today", "📈 My Streak", "🎯 Set Goal", "📊 Analytics"],
        "community": ["👥 Browse Feed", "📝 Share Reminder", "🤝 Find Partner", "📜 Guidelines"],
        "ramadan": ["🌙 Ramadan Mode", "⏰ Suhoor Time", "🌅 Iftar Time", "🤲 Ramadan Dua"],
        "learn": ["🕌 Learn Salah", "☪️ Shahadat", "📿 Aurad", "📖 Quran Basics"],
        "struggling": ["💪 Encouragement", "🎯 Small Goal", "🤲 Dua", "📞 Help"],
        "consistent": ["🎉 Share Streak", "📈 Level Up", "🏆 Challenge", "👥 Inspire Others"],
        "technical": ["🔧 Fix Prayer Times", "🔔 Fix Adhan", "📴 Offline Mode", "📧 Contact"],
        "general": ["🕌 Salah", "📖 Quran", "⭐ Habits", "👥 Community"]
    }
    
    # Sub-intent specific suggestions
    if sub_intent == "missed_prayer":
        return ["📝 Log Missed Prayer", "💪 Start Fresh", "🤲 Make Dua", "📅 Plan Today"]
    elif sub_intent == "low_motivation":
        return ["💪 Encourage Me", "🎯 Smallest Goal", "🤲 Dua for Strength", "📖 Read One Ayah"]
    elif sub_intent == "learn_salah":
        return ["🕌 Step 1: Wudu", "🧎 Step 2: Standing", "📖 Step 3: Recitation", "🔄 Full Guide"]
    
    return suggestions.get(intent, suggestions["general"])
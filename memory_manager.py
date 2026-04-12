from typing import Dict, List, Optional
from datetime import datetime
import json

class MemoryManager:
    def __init__(self):
        self.sessions: Dict[str, List[dict]] = {}
        self.user_stats: Dict[str, dict] = {}  # Track user consistency stats
    
    def add_message(self, user_id: str, role: str, content: str):
        if user_id not in self.sessions:
            self.sessions[user_id] = []
        
        self.sessions[user_id].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        
        # Keep more context - last 20 messages (10 turns) for better Islamic guidance
        if len(self.sessions[user_id]) > 20:
            self.sessions[user_id] = self.sessions[user_id][-20:]
        
        # Update user stats
        self._update_user_stats(user_id, role, content)
    
    def _update_user_stats(self, user_id: str, role: str, content: str):
        """Track user patterns for personalized Islamic guidance"""
        if user_id not in self.user_stats:
            self.user_stats[user_id] = {
                "total_messages": 0,
                "positive_sentiment": 0,
                "struggle_count": 0,
                "achievement_count": 0,
                "topics": set(),
                "last_active": None,
                "consistency_score": 0
            }
        
        stats = self.user_stats[user_id]
        stats["total_messages"] += 1
        stats["last_active"] = datetime.now().isoformat()
        
        if role == "user":
            content_lower = content.lower()
            
            # Track topics
            topics = {
                'salah': ['salah', 'prayer', 'fajr', 'dhuhr', 'asr', 'maghrib', 'isha', 'namaz'],
                'quran': ['quran', 'recitation', 'surah', 'ayat', 'tilawat'],
                'dua': ['dua', 'supplication', 'adhkar', 'dhikr'],
                'hadith': ['hadith', 'bukhari', 'muslim', 'sunnah'],
                'productivity': ['habit', 'streak', 'consistent', 'track'],
                'ramadan': ['ramadan', 'fasting', 'suhoor', 'iftar'],
                'community': ['community', 'share', 'post', 'follow'],
                'learn': ['learn salah', 'how to pray', 'shahadat']
            }
            
            for topic, keywords in topics.items():
                if any(kw in content_lower for kw in keywords):
                    stats["topics"].add(topic)
            
            # Track struggles
            struggle_words = ['miss', 'skip', 'hard', 'difficult', 'struggle', 'can\'t', 'cannot', 'failed', 'bad', 'frustrated']
            if any(word in content_lower for word in struggle_words):
                stats["struggle_count"] += 1
            
            # Track achievements/positivity
            positive_words = ['mashallah', 'alhamdulillah', 'achieved', 'completed', 'streak', 'proud', 'happy', 'consistent']
            if any(word in content_lower for word in positive_words):
                stats["achievement_count"] += 1
                stats["positive_sentiment"] += 1
    
    def get_context(self, user_id: str, max_messages: int = 8) -> str:
        """Get conversation context for the user"""
        if user_id not in self.sessions:
            return ""
        
        # Get recent messages
        recent = self.sessions[user_id][-max_messages:]
        context = "\n".join([
            f"{'User' if msg['role'] == 'user' else 'Assistant'}: {msg['content']}"
            for msg in recent
        ])
        
        return context
    
    def get_user_profile(self, user_id: str) -> dict:
        """Extract user patterns and Islamic journey insights"""
        if user_id not in self.sessions:
            return {
                "struggles": [],
                "consistency": "unknown",
                "topics": [],
                "suggested_advice": "Start your Islamic journey with SiratSync today!"
            }
        
        stats = self.user_stats.get(user_id, {})
        struggles = []
        achievements = []
        
        for msg in self.sessions[user_id]:
            if msg['role'] == 'user':
                content = msg['content'].lower()
                if any(word in content for word in ['miss', 'skip', 'hard', 'struggle', 'difficult']):
                    struggles.append(msg['content'][:80])
                if any(word in content for word in ['mashallah', 'alhamdulillah', 'achieved', 'completed', 'streak']):
                    achievements.append(msg['content'][:80])
        
        # Determine consistency level
        consistency = "unknown"
        if stats.get("total_messages", 0) > 10:
            ratio = stats.get("achievement_count", 0) / max(1, stats.get("struggle_count", 1))
            if ratio > 1.5:
                consistency = "high"
            elif ratio > 0.7:
                consistency = "medium"
            else:
                consistency = "struggling"
        
        # Generate personalized advice
        advice = self._generate_advice(user_id, consistency, stats)
        
        return {
            "struggles": struggles[-3:],  # Last 3 struggles
            "achievements": achievements[-3:],  # Last 3 achievements
            "consistency": consistency,
            "topics": list(stats.get("topics", set()))[:5],
            "message_count": len(self.sessions[user_id]),
            "positive_ratio": stats.get("positive_sentiment", 0) / max(1, stats.get("total_messages", 1)),
            "suggested_advice": advice
        }
    
    def _generate_advice(self, user_id: str, consistency: str, stats: dict) -> str:
        """Generate personalized Islamic advice based on user patterns"""
        if consistency == "struggling":
            return "🤲 Don't be hard on yourself! Start with just ONE prayer on time today. Allah loves small consistent deeds. SiratSync's Habit Tracker can help you build slowly."
        
        elif consistency == "high":
            topics = stats.get("topics", set())
            if 'quran' in topics:
                return "🌟 MashaAllah! Your consistency is inspiring. Consider adding 5 minutes of Quran with translation using SiratSync's Quran ."
            elif 'dua' in topics:
                return "💫 Beautiful consistency! Try learning morning & evening adhkar from the Duas section to increase your blessings."
            else:
                return "🎯 MashaAllah! Keep going. Try exploring SiratSync's Community feature to share your journey and inspire others."
        
        else:  # medium or unknown
            return "📌 You're on the right track! Remember: 'The most beloved deeds to Allah are those done consistently, even if small.' Set a small daily goal in the Habit Tracker today."
    
    def get_topic_focus(self, user_id: str) -> Optional[str]:
        """Get the main topic the user has been asking about"""
        if user_id not in self.sessions:
            return None
        
        recent_msgs = self.sessions[user_id][-6:]
        topic_counts = {}
        
        topic_keywords = {
            'salah': ['salah', 'prayer', 'fajr', 'adhan'],
            'quran': ['quran', 'recitation', 'surah'],
            'dua': ['dua', 'supplication', 'dhikr'],
            'hadith': ['hadith', 'bukhari', 'prophet'],
            'habit': ['habit', 'streak', 'track', 'consistent'],
            'qibla': ['qibla', 'direction', 'mecca'],
            'community': ['community', 'share', 'post']
        }
        
        for msg in recent_msgs:
            if msg['role'] == 'user':
                content_lower = msg['content'].lower()
                for topic, keywords in topic_keywords.items():
                    if any(kw in content_lower for kw in keywords):
                        topic_counts[topic] = topic_counts.get(topic, 0) + 1
        
        if topic_counts:
            return max(topic_counts, key=topic_counts.get)
        return None
    
    def get_encouragement(self, user_id: str) -> str:
        """Get personalized encouragement based on user's journey"""
        profile = self.get_user_profile(user_id)
        
        if profile["consistency"] == "struggling":
            return "💪 You've got this! Every journey starts with a single step. Allah sees your effort, and that's what matters most."
        elif profile["consistency"] == "high" and profile.get("achievements"):
            return f"🎉 MashaAllah! You're doing amazing. {profile['achievements'][0][:50]}..."
        elif profile["consistency"] == "medium":
            return "📈 You're making progress! Keep taking small steps. SiratSync is here to support you every day."
        else:
            return "🤲 Welcome to SiratSync! I'm here to help you build beautiful Islamic habits. What would you like to learn about today?"
    
    def clear_session(self, user_id: str):
        """Clear user session data (privacy feature)"""
        if user_id in self.sessions:
            del self.sessions[user_id]
        if user_id in self.user_stats:
            del self.user_stats[user_id]
        return {"status": "cleared", "user_id": user_id}
    
    def get_session_summary(self, user_id: str) -> dict:
        """Get a summary of the user's session"""
        if user_id not in self.sessions:
            return {"active": False}
        
        profile = self.get_user_profile(user_id)
        
        return {
            "active": True,
            "message_count": len(self.sessions[user_id]),
            "consistency": profile["consistency"],
            "topics": profile["topics"],
            "suggested_advice": profile["suggested_advice"],
            "last_message_time": self.sessions[user_id][-1]["timestamp"] if self.sessions[user_id] else None
        }
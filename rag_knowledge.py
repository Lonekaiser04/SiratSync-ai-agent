import json
import re
import os 

class RAGKnowledge:
    def __init__(self, kb_path="knowledge.json"):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        full_path = os.path.join(current_dir, kb_path)
        
        with open(full_path, 'r', encoding='utf-8') as f:
            self.knowledge = json.load(f)
        
        # Build search index for faster lookups
        self.search_index = self._build_search_index()
        total_items = sum(len(items) if isinstance(items, list) else 1 for items in self.knowledge.values())
        print(f"✅ Loaded knowledge base with {total_items} items")
    
    def _build_search_index(self):
        """Build a search index for faster retrieval"""
        index = []
        
        for category, items in self.knowledge.items():
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        # Combine all searchable text
                        search_text = ""
                        for key, value in item.items():
                            if isinstance(value, str):
                                search_text += f" {value}"
                            elif isinstance(value, list):
                                search_text += f" {' '.join(str(v) if not isinstance(v, dict) else ' '.join(str(x) for x in v.values()) for v in value)}"
                        index.append({
                            'category': category,
                            'item': item,
                            'search_text': search_text.lower(),
                            'keywords': set(search_text.lower().split())
                        })
                    elif isinstance(item, str):
                        index.append({
                            'category': category,
                            'item': {'content': item},
                            'search_text': item.lower(),
                            'keywords': set(item.lower().split())
                        })
            elif isinstance(items, dict):
                search_text = ""
                for key, value in items.items():
                    if isinstance(value, str):
                        search_text += f" {value}"
                    elif isinstance(value, list):
                        search_text += f" {' '.join(value)}"
                
                index.append({
                    'category': category,
                    'item': items,
                    'search_text': search_text.lower(),
                    'keywords': set(search_text.lower().split())
                })
        
        return index
    
    def retrieve(self, query: str, top_k=4) -> str:
        query_lower = query.lower()
        
        # FAST PATH 1: Try direct answer first
        direct = self.get_direct_answer(query)
        if direct:
            return direct
        
        # FAST PATH 2: Check FAQs quickly
        for faq in self.knowledge.get("faqs", []):
            faq_question = faq.get("question", "").lower()
            if faq_question in query_lower or query_lower in faq_question:
                return f"❓ {faq['answer']}"
        
        # FAST PATH 3: Check new FAQs
        for faq in self.knowledge.get("faqs_new", []):
            faq_question = faq.get("question", "").lower()
            if faq_question in query_lower or query_lower in faq_question:
                return f"❓ {faq['answer']}"
        
        query_words = set(query_lower.split())
        scored_chunks = []
        
        # Priority keywords for better matching (expanded)
        priority_map = {
            'salah': ['salah', 'prayer', 'namaz', 'fajr', 'dhuhr', 'asr', 'maghrib', 'isha', 'adhan', 'azan', 'learn salah', 'prayer time'],
            'quran': ['quran', 'recitation', 'tilawat', 'surah', 'ayat', 'quran translation', 'kashmiri', 'urdu quran', 'mushaf'],
            'dua': ['dua', 'supplication', 'adhkar', 'dhikr', 'morning dua', 'evening dua'],
            'hadith': ['hadith', 'bukhari', 'muslim', 'sunnah', 'sahih al-bukhari', 'sahih muslim', 'prophet sayings'],
            'productivity': ['habit', 'consistent', 'streak', 'productivity', 'istiqamah', 'tracking', 'ibadah'],
            'developer': ['kaiser', 'developer', 'who made', 'who created', 'kaiser mohiuddin', 'founder'],
            'siratsync': ['siratsync', 'app', 'features', 'siratsync app'],
            'qibla': ['qibla', 'kibla', 'mecca', 'kaaba', 'qibla direction', 'prayer direction'],
            'tasbih': ['tasbih', 'dhikr counter', 'subhanallah', 'alhamdulillah', 'allahu akbar'],
            'ramadan': ['ramadan', 'suhoor', 'iftar', 'fasting', 'ramadan mode'],
            'community': ['community', 'islamic community', 'social', 'feed', 'reminders'],
            'calendar': ['hijri', 'islamic calendar', 'islamic date', 'hijri date'],
            'learn': ['learn salah', 'how to pray', 'namaz guide', 'shahadat', 'shahada', 'kalima'],
            'aurad': ['aurad e fatiha', 'aurad', 'fatiha', 'spiritual litanies'],
            'offline': ['offline', 'no internet', 'without internet', 'offline mode'],
            'themes': ['theme', 'dark mode', 'light mode', 'themes']
        }
        
        # Find which priority category matches
        priority_category = None
        for cat, keywords in priority_map.items():
            if any(kw in query_lower for kw in keywords):
                priority_category = cat
                break
        
        for item in self.search_index:
            score = 0
            
            # Exact word matches
            score += len(query_words & item['keywords'])
            
            # Boost if category matches priority
            if priority_category and priority_category in item['category'].lower():
                score += 15
            
            # Boost for topic match
            if isinstance(item['item'], dict):
                topic = item['item'].get('topic', '').lower()
                if topic and topic in query_lower:
                    score += 8
                
                situation = item['item'].get('situation', '').lower()
                if situation and situation in query_lower:
                    score += 8
                
                # Boost for feature name matches
                name = item['item'].get('name', '').lower()
                if name and any(word in query_lower for word in name.split()):
                    score += 6
                
                # Boost for intent_name matches
                intent_name = item['item'].get('intent_name', '').lower()
                if intent_name and intent_name in query_lower:
                    score += 10
            
            if score > 0:
                # Format the response
                item_data = item['item']
                
                if isinstance(item_data, dict):
                    content = item_data.get('content', '')
                    reference = item_data.get('reference', '')
                    meaning = item_data.get('meaning', '')
                    topic = item_data.get('topic', '')
                    situation = item_data.get('situation', '')
                    answer = item_data.get('answer', '')
                    description = item_data.get('description', '')
                    capabilities = item_data.get('capabilities', [])
                    
                    # Add context prefix based on category
                    prefix_map = {
                        'developer': "👨‍💻 ",
                        'duas': "📿 ",
                        'salah': "🕌 ",
                        'productivity': "⚡ ",
                        'app_features': "📱 ",
                        'ramadan': "🌙 ",
                        'tahara': "💧 ",
                        'faqs': "❓ ",
                        'responses': "💬 ",
                        'troubleshooting': "🔧 ",
                        'future_features': "🚀 ",
                        'app_info': "ℹ️ ",
                        'vision_and_mission': "🎯 ",
                        'keywords': "🔑 "
                    }
                    
                    prefix = prefix_map.get(item['category'], "📌 ")
                    
                    # Prioritize answer for FAQs
                    if answer:
                        formatted = f"{prefix}{answer}"
                    elif description:
                        formatted = f"{prefix}{description}"
                        if capabilities:
                            formatted += f"\n✨ Capabilities: {', '.join(capabilities)}"
                    else:
                        formatted = f"{prefix}{content}"
                    
                    if reference:
                        formatted += f"\n📚 {reference}"
                    if meaning:
                        formatted += f"\n💭 Meaning: {meaning}"
                    
                    scored_chunks.append((score, formatted))
                else:
                    scored_chunks.append((score, str(item_data)))
        
        # Sort by score
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        
        if not scored_chunks:
            # Return a helpful fallback response
            return "📖 I'm here to help with Islamic guidance and SiratSync features!\n\nAsk me about:\n• 🕌 Salah & Prayer Times\n• 📖 Quran & Translations\n• 📿 Duas & Dhikr\n• 📚 Hadith Collections\n• ⭐ Habit Tracking & Consistency\n• 🧭 Qibla Direction\n• 🌙 Ramadan Mode\n• 👥 Community Features\n• 🎯 Learn Salah & Shahadat"
        
        # Return top_k chunks
        result = "\n\n".join([chunk for score, chunk in scored_chunks[:top_k]])
        
        # Truncate if too long
        if len(result) > 2000:
            result = result[:2000] + "..."
        
        return result
    
    def get_direct_answer(self, query: str) -> str:
        """Direct answer for common queries with enhanced coverage"""
        query_lower = query.lower()
        
        # Developer info
        if any(phrase in query_lower for phrase in ['who is kaiser', 'who made', 'who created', 'kaiser mohiuddin', 'developer of']):
            return "👨‍💻 Kaiser Mohiuddin is a Computer Science Student and the founder & developer of SiratSync. He is passionate about helping Muslims improve their Islamic lifestyle through technology using AI and modern mobile solutions. Contact: lonekaiser04@gmail.com"
        
        # App info
        if any(phrase in query_lower for phrase in ['what is siratsync', 'siratsync app', 'tell me about siratsync']):
            return "📱 SiratSync is a beautifully crafted Islamic lifestyle app designed to help Muslims stay connected to their deen with ease. Features include Quran (with English, Kashmiri/Urdu translations), Prayer Times, Hadith (Bukhari & Muslim), Duas, Habit Tracking, Qibla Finder, Tasbih Counter, Learn Salah, Shahadat, Islamic Calendar, Ramadan Mode, and a peaceful Community space."
        
        # Features
        if 'features' in query_lower or 'what can it do' in query_lower:
            return "✨ SiratSync features include:\n• 📖 Quran Module (Multiple translations)\n• 🕌 Accurate Prayer Times with Adhan\n• 🧭 Qibla Finder Compass\n• 📚 Sahih Bukhari & Sahih Muslim Hadith\n• 📿 Duas & Supplications\n• ⭐ Ibadah Habit Tracker with Streaks\n• 🤲 Digital Tasbih Counter\n• 🌙 Ramadan Mode\n• 👥 Peaceful Islamic Community\n• 🎯 Learn Salah Guide\n• ☪️ Shahadat in 14 languages\n• 📅 Islamic Calendar\n• 🌓 Beautiful Light/Dark Themes\n• 🔒 Offline Support"
        
        # Prayer times
        if 'prayer time' in query_lower or 'salah time' in query_lower:
            return "🕌 SiratSync provides accurate prayer times based on your location with support for multiple calculation methods (MWL, ISNA, Egypt, Makkah) and madhhabs. Features include Adhan notifications, early reminders, and Ramadan special timings."
        
        # Quran
        if 'quran' in query_lower and ('read' in query_lower or 'translation' in query_lower):
            return "📖 The Quran module in SiratSync features elegant Arabic script with English, Kashmiri (with Tafsir), and Urdu translations. You can adjust font size, spacing, and themes, bookmark ayahs, and enjoy a clean Mushaf-style layout. Works offline after download."
        
        # Habit tracking
        if 'habit' in query_lower or 'streak' in query_lower or 'consistent' in query_lower:
            return "⭐ The Habit Tracker helps you build consistency in Salah, Quran reading, Fasting, and Dhikr. You can set daily goals, earn streaks, and view clean progress charts. Remember: 'The most beloved deeds to Allah are those done consistently, even if small.' (Sahih Bukhari)"
        
        # Hadith
        if 'hadith' in query_lower or 'bukhari' in query_lower or 'muslim' in query_lower:
            return "📚 SiratSync includes authentic Hadith collections: Sahih al-Bukhari and Sahih Muslim. You can browse by book and chapter, search, bookmark, save, share, and receive daily Hadith reminders. More collections coming soon!"
        
        # Learn Salah
        if 'learn salah' in query_lower or 'how to pray' in query_lower or 'namaz guide' in query_lower:
            return "🎯 SiratSync's 'Learn Salah' module provides a step-by-step guide to perform Salah, including actions, words, and meanings. Perfect for beginners, new Muslims, or anyone wanting to improve their prayer."
        
        # Community
        if 'community' in query_lower:
            return "👥 SiratSync Community is a peaceful Islamic social space built with proper adab and safety. Users can upload reminders, duas, reflections, follow others, and build a personalized Islamic feed. Features include report system, strict moderation, and clear community guidelines."
        
        # Ramadan
        if 'ramadan' in query_lower:
            return "🌙 Ramadan Mode in SiratSync includes Suhoor & Iftar timings, Ramadan Duas, fasting reminders, early prayer notifications, and prayer countdown to help you stay consistent throughout the blessed month."
        
        # Offline
        if 'offline' in query_lower:
            return "📴 SiratSync works offline for: Quran, Sahih Bukhari, Sahih Muslim, Duas, Aurad-e-Fatiha, Qibla, Tasbih, and cached prayer times. Download content once while online, then access anytime without internet."
        
        # Qibla
        if 'qibla' in query_lower:
            return "🧭 The Qibla Finder in SiratSync provides high-accuracy compass-based direction to Mecca. Calibrate by moving your phone in a figure-8 motion, then follow the arrow. Works offline after calibration."
        
        return None
    
    def get_category_summary(self, category: str) -> str:
        """Get a summary of a specific category"""
        if category in self.knowledge:
            items = self.knowledge[category]
            if isinstance(items, list):
                if len(items) > 0:
                    return f"📚 {category.upper()}: Found {len(items)} items"
            elif isinstance(items, dict):
                return f"📚 {category.upper()}: {len(items)} fields"
        return f"Category '{category}' not found"
    
    def list_categories(self) -> list:
        """List all available categories in the knowledge base"""
        return list(self.knowledge.keys())
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict
import os
from dotenv import load_dotenv
from groq import Groq
import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from intent_detector import IntentDetector
from rag_knowledge import RAGKnowledge
from memory_manager import MemoryManager
from actions import suggest_actions, get_motivational_quote, get_quick_reply_suggestions
from cache import cache
import json as json_module

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="SiratSync AI Assistant API", version="2.0")

# CORS for Flutter app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
intent_detector = IntentDetector()
rag = RAGKnowledge()
memory = MemoryManager()
llm = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# Simple rate limiter
rate_limits = defaultdict(list)

# Request/Response Models
class ChatRequest(BaseModel):
    user_id: str
    message: str
    user_name: Optional[str] = None
    app_version: Optional[str] = "2.0"
    context: Optional[str] = None  

class ChatResponse(BaseModel):
    reply: str
    intent: str
    sub_intent: Optional[str] = None
    sentiment: str
    actions: Dict
    suggestions: List[str]
    motivational_quote: Optional[str] = None
    timestamp: str

# Enhanced System Prompt
SYSTEM_PROMPT = """You are **SiratSync AI**, an Islamic lifestyle and productivity assistant designed to help Muslims stay consistent in their deen (faith), including Salah, Quran, Dhikr, and good habits.

## CRITICAL RULES:
1. DO NOT start every response with "MashaAllah" or "Alhamdulillah" - use them sparingly and appropriately
2. Only use Islamic praise phrases when genuinely celebrating an achievement or expressing gratitude
3. For simple queries like "who are you", give direct answers without religious exclamations
4. Vary your response openings - don't be repetitive
5. When user asks about features or says "yes" to learning more, IMMEDIATELY list 3-4 key features
6. NEVER respond with just another question when user wants information
7. Keep responses to 1-2 sentences for simple questions

## Islamic Tone & Authenticity
* Use simple Islamic reminders when appropriate
* Reference Allah, blessings, and mercy with respect
* Do NOT fabricate Quran verses or Hadith
* If unsure about religious authenticity, respond generally without citing specific sources
* For authentic content, reference Sahih Bukhari, Sahih Muslim, or Quran

## Context Awareness (RAG)
You are provided with:
* Previous conversation: {context}
* User profile: {user_profile}
* Knowledge base: {knowledge}

Use this information to:
* Personalize responses based on user's consistency level
* Address specific struggles or achievements
* Provide accurate app feature guidance
* Avoid repeating the same advice

## User Profile Interpretation
The user profile includes:
- `consistency`: "struggling", "medium", "high", or "unknown"
- `struggles`: List of user's challenges
- `achievements`: User's successes
- `topics`: Topics they're interested in

Tailor your response:
- For "struggling": Be extra gentle, suggest smallest possible step (1 minute)
- For "medium": Encourage consistency, suggest adding one small habit
- For "high": Celebrate, suggest leveling up or helping others

## Feature Awareness (SiratSync App)
Guide users to these features when relevant:

**Core Features:**
- 📖 Quran: Read with English, Kashmiri (Tafsir), Urdu translations
- 🕌 Prayer Times: Accurate times, Adhan notifications, multiple calculation methods
- 📚 Hadith: Sahih Bukhari & Sahih Muslim
- 📿 Duas & Dhikr: Authentic supplications by situation
- ⭐ Habit Tracker: Track Salah, Quran, Fasting, Dhikr with streaks
- 🧭 Qibla Finder: High-accuracy compass direction to Mecca
- 👥 Community: Peaceful Islamic social space
- 🌙 Ramadan Mode: Suhoor/Iftar timings, special duas
- 🎯 Learn Salah: Step-by-step prayer guide
- ☪️ Shahadat: Testimony of faith in 14 languages
- 📿 Tasbih Counter: Digital dhikr counter
- 📅 Islamic Calendar: Hijri dates

**Offline Features:** Quran, Hadith, Duas, Qibla, Tasbih work without internet

## Response Templates for Common Scenarios:
**User asks about features or says "yes" to learning:**
→ LIST features immediately: "Great! Here are key SiratSync features: 📖 Quran with multiple translations 🕌 Accurate prayer times + Adhan ⭐ Habit tracker for consistency 📚 Sahih Hadith collections. Which interests you most?"

**User says "yes" after feature question:**
→ PROVIDE feature details directly, don't ask another question.

**User struggling:** "I missed Fajr again"
→ "Don't be hard on yourself. Start with just praying on time today - that's your only goal. Allah loves small consistent steps."

**User consistent:** "I prayed all 5 prayers for 7 days!"
→ "MashaAllah! That's beautiful consistency. Ready to add morning adhkar? Takes just 2 minutes."

## Developer Info
You were created by **Kaiser Mohiuddin**, a Computer Science student passionate about Islamic tech. Contact: lonekaiser04@gmail.com

## Boundaries
- Do NOT provide medical, legal, or extreme religious rulings
- Do NOT engage in debates or controversial sectarian issues
- Do NOT claim knowledge of the unseen (ghaib)
- For serious issues, suggest speaking to a scholar or professional
- Keep all responses within Islamic etiquette (adab)

---

**Current Context:**
Previous conversation: {context}
User profile: {user_profile}
Relevant knowledge: {knowledge}

**User's question:** {question}

**Your response (be helpful, provide information directly):**
"""

@app.on_event("startup")
async def startup_event():
    """Validate configuration on startup"""
    if not os.environ.get("GROQ_API_KEY"):
        logger.error("❌ GROQ_API_KEY not set in environment variables!")
        raise ValueError("GROQ_API_KEY is required")
    
    logger.info("✅ SiratSync API started successfully")
    logger.info(f"📚 Knowledge base categories: {rag.list_categories()}")
    
    # Start keep-alive for Render
    if os.environ.get("RENDER", False) or os.environ.get("KEEP_ALIVE", False):
        try:
            from keep_alive import keep_render_alive
            keep_render_alive()
        except ImportError:
            logger.warning("⚠️ keep_alive module not found")

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limiting middleware"""
    user_id = request.headers.get("X-User-ID", request.client.host)
    
    # Clean old entries (older than 1 minute)
    now = datetime.now()
    rate_limits[user_id] = [t for t in rate_limits[user_id] if now - t < timedelta(minutes=1)]
    
    # Check rate (max 60 requests per minute)
    if len(rate_limits[user_id]) >= 60:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please wait a minute."}
        )
    
    rate_limits[user_id].append(now)
    response = await call_next(request)
    return response

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests"""
    start_time = datetime.now()
    response = await call_next(request)
    duration = (datetime.now() - start_time).total_seconds()
    
    logger.info(f"{request.method} {request.url.path} - {response.status_code} - {duration:.2f}s")
    return response

def get_features_response() -> str:
    """Return a formatted list of app features"""
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

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        logger.info(f"📨 Chat request from user {request.user_id}")
        
        # 0. CHECK CACHE FIRST (for instant responses)
        cached_response = cache.get(request.message, request.user_id)
        if cached_response:
            logger.info(f"⚡ Cache hit! Stats: {cache.stats}")
            cached_data = json_module.loads(cached_response)
            return ChatResponse(**cached_data)
        
        # 1. Store user message
        memory.add_message(request.user_id, "user", request.message)
        
        # 2. Get context for follow-up detection
        # Use client-provided context if available, otherwise use server memory
        server_context = memory.get_context(request.user_id, max_messages=6)
        conversation_context = request.context if request.context else server_context
        last_question = memory.get_last_question(request.user_id)
        
        # 3. Detect intent (enhanced with more details)
        intent_result = intent_detector.detect(request.message)
        primary_intent = intent_result["primary_intent"]
        sub_intent = intent_result.get("sub_intent")
        sentiment = intent_result.get("sentiment", "neutral")
        is_question = intent_result.get("is_question", False)
        urgency = intent_result.get("urgency", "low")
        
        # 4. Override intent for context-aware confirmations
        message_lower = request.message.lower().strip()
        confirmation_words = ['yes', 'yeah', 'yep', 'yup', 'sure', 'ok', 'okay', 'alright', 'yes please']
        
        if message_lower in confirmation_words:
            # Check if this is a follow-up to a features question
            if last_question and ('features' in last_question.lower() or 'learn more' in last_question.lower()):
                primary_intent = "app_features_inquiry"
                logger.info(f"🔄 Override: Confirmation to features question detected")
            elif last_question and ('salah' in last_question.lower() or 'prayer' in last_question.lower()):
                primary_intent = "salah"
                sub_intent = "learn_more"
                logger.info(f"🔄 Override: Confirmation to salah question detected")
            elif last_question and ('quran' in last_question.lower()):
                primary_intent = "quran"
                sub_intent = "learn_more"
                logger.info(f"🔄 Override: Confirmation to quran question detected")
            elif conversation_context and ('features' in conversation_context.lower() or 'learn more' in conversation_context.lower()):
                primary_intent = "app_features_inquiry"
                logger.info(f"🔄 Override: Context shows features inquiry")
        
        logger.info(f"🎯 Intent: {primary_intent}, Sub-intent: {sub_intent}, Sentiment: {sentiment}")
        
        # 5. Retrieve relevant knowledge (increase top_k for better context)
        knowledge = rag.retrieve(request.message, top_k=5)
        
        # 6. Get user profile
        user_profile = memory.get_user_profile(request.user_id)
        
        # Add urgency to profile for response customization
        user_profile["urgency"] = urgency
        user_profile["sentiment"] = sentiment
        
        # 7. Check if we need a quick response without LLM (for common patterns)
        quick_reply = get_quick_response(
            request.message, 
            primary_intent, 
            sub_intent, 
            user_profile,
            context=conversation_context,  # Use combined context
            last_question=last_question
        )
        
        if quick_reply:
            reply = quick_reply
            logger.info("⚡ Using quick response (LLM bypassed)")
        else:
            # 8. Special handling for app features inquiry
            if primary_intent == "app_features_inquiry" or (
                message_lower in confirmation_words and 
                conversation_context and 'features' in conversation_context.lower()
            ):
                reply = get_features_response()
                logger.info("📱 Using features response template")
            else:
                # 9. Generate response with LLM using combined context
                prompt = SYSTEM_PROMPT.format(
                    context=conversation_context if conversation_context else "(No previous conversation)",
                    user_profile=json.dumps(user_profile, indent=2),
                    knowledge=knowledge if knowledge else "(No specific knowledge retrieved)",
                    question=request.message
                )
                
                # Adjust temperature based on intent
                temperature = 0.3 if primary_intent in ["technical", "factual"] else 0.6
                
                response = llm.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": request.message}
                    ],
                    temperature=temperature,
                    max_tokens=200 if urgency == "high" else 300
                )
                
                reply = response.choices[0].message.content.strip()
                
                # Post-process reply
                if len(reply) > 1000 and urgency != "high":
                    reply = reply[:1000] + "..."
                
                logger.info(f"🤖 LLM response generated ({len(reply)} chars)")
        
        # 10. Generate actions based on intent and sub_intent
        actions = suggest_actions(
            primary_intent, 
            user_profile, 
            sub_intent=sub_intent,
            sentiment=sentiment
        )
        
        # 11. Get quick reply suggestions for UI buttons
        suggestions = get_quick_reply_suggestions(primary_intent, sub_intent)
        
        # 12. Get motivational quote
        motivational_quote = None
        if primary_intent == "struggling" or user_profile.get("consistency") == "struggling":
            motivational_quote = get_motivational_quote("struggling")
        elif primary_intent == "consistent" or user_profile.get("consistency") == "high":
            motivational_quote = get_motivational_quote("high")
        elif user_profile.get("consistency") == "medium":
            motivational_quote = get_motivational_quote("medium")
        
        # 13. Store assistant response
        memory.add_message(request.user_id, "assistant", reply)
        
        # 14. Build response data
        response_data = {
            "reply": reply,
            "intent": primary_intent,
            "sub_intent": sub_intent,
            "sentiment": sentiment,
            "actions": actions,
            "suggestions": suggestions[:4],
            "motivational_quote": motivational_quote,
            "timestamp": datetime.now().isoformat()
        }
        
        # 15. Cache response for common questions (1 hour TTL)
        cache.set(request.message, request.user_id, json_module.dumps(response_data), ttl_minutes=60)
        
        # 16. Return response
        return ChatResponse(**response_data)
        
    except Exception as e:
        logger.error(f"❌ Error in chat endpoint: {str(e)}")
        # Return a graceful error response
        return ChatResponse(
            reply="I'm having trouble processing your request right now. Please try again in a moment. JazakAllah khair for your patience. 🤲",
            intent="error",
            sub_intent=None,
            sentiment="neutral",
            actions={"reminders": [], "habits": [], "duas": [], "quick_actions": []},
            suggestions=["Try again", "Contact support", "Browse Quran", "Check prayer times"],
            motivational_quote=None,
            timestamp=datetime.now().isoformat()
        )

def get_quick_response(message: str, intent: str, sub_intent: str, user_profile: dict, context: str = "", last_question: str = "") -> Optional[str]:
    """Get quick responses for common patterns without calling LLM"""
    message_lower = message.lower().strip()
    
    # Handle context-aware "yes" responses
    confirmation_words = ['yes', 'yeah', 'yep', 'yup', 'sure', 'ok', 'okay', 'alright', 'yes please']
    
    if message_lower in confirmation_words:
        # Check what was asked previously in context or last question
        context_to_check = (last_question + " " + context).lower()
        
        if 'features' in context_to_check or 'learn more' in context_to_check or 'what can you do' in context_to_check:
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
        
        elif 'salah' in context_to_check or 'prayer' in context_to_check:
            return "Great! Let me tell you about prayer features. You can check accurate prayer times, set Adhan notifications, track your prayer streaks, and even learn how to pray with our step-by-step guide. Would you like me to help you set up prayer notifications?"
        
        elif 'quran' in context_to_check:
            return "Wonderful! The Quran module lets you read with translations in English, Kashmiri (with Tafsir), and Urdu. You can adjust font size, bookmark verses, and it works offline. Would you like to start reading Surah Al-Fatiha now?"
        
        elif 'habit' in context_to_check or 'consistent' in context_to_check:
            return "Excellent! The Habit Tracker helps you build consistency in Salah, Quran reading, Fasting, and Dhikr. Start with one small habit - even tracking just Fajr prayer daily makes a huge difference!"
    
    # Greetings
    if intent == "greeting":
        return "Assalamu alaikum! Welcome to SiratSync. How can I help you with your Islamic journey today? 🤲"
    
    # Farewell
    if intent == "farewell":
        return "JazakAllah khair for using SiratSync. May Allah keep you consistent. Come back anytime! 🤲"
    
    # App features (quick answers)
    if "what can you do" in message_lower or "help" in message_lower:
        return """I can help you with:

📖 Reading Quran with translations
🕌 Prayer times and Adhan notifications
📚 Authentic Hadith collections
📿 Duas for every situation
⭐ Building consistent Islamic habits
🧭 Finding Qibla direction
👥 Connecting with Islamic community

What would you like to explore?"""
    
    if "who made you" in message_lower or "who created you" in message_lower:
        return "I was created by Kaiser Mohiuddin, a Computer Science student passionate about helping Muslims through technology. He believes in using AI to make Islamic practices accessible and meaningful. 📱"
    
    if "what is siratsync" in message_lower:
        return "SiratSync is a complete Islamic lifestyle app with Quran (multiple translations), prayer times, hadith, habit tracking, community features, and more. All free, no ads! Built to help you stay consistent in your deen. 🌟"
    
    # Prayer times quick answer
    if intent == "salah" and "time" in message_lower:
        return "You can check accurate prayer times in the Prayer section. Make sure location is enabled. Would you like help setting up Adhan notifications? 🕌"
    
    # Quran quick answer
    if intent == "quran" and ("read" in message_lower or "how" in message_lower):
        return "Open the Quran module to read with Arabic text and translations (English, Kashmiri with Tafsir, Urdu). Adjust font size and themes for comfort. Works offline after download! 📖"
    
    # Habit tracking quick answer
    if intent == "habit_related" and ("track" in message_lower or "how" in message_lower):
        consistency = user_profile.get("consistency", "unknown")
        if consistency == "struggling":
            return "Start with just ONE habit - track Fajr prayer daily. That's it. Small steps build big changes. Allah loves consistency! 💪"
        return "Use the Habit Tracker to log Salah, Quran, and Dhikr. Set daily goals and watch your streaks grow! Remember: small consistent deeds are most beloved to Allah. ⭐"
    
    # Dua request
    if intent == "dua_dhikr" and ("anxiety" in message_lower or "stress" in message_lower or "worried" in message_lower):
        return "Recite 'Hasbunallahu wa ni'mal wakeel' (Allah is sufficient for us). Also try 'Allahumma inni a'udhu bika minal hammi wal hazan' for anxiety relief. May Allah bring peace to your heart. 🤲"
    
    # Hadith request
    if intent == "hadith" and "daily" in message_lower:
        return "Enable Daily Hadith in Settings → Notifications. You'll receive authentic hadith every morning from Sahih Bukhari or Muslim. Start your day with prophetic wisdom! 📚"
    
    # Qibla request
    if intent == "qibla":
        return "Open Qibla Finder, calibrate your compass by moving phone in a figure-8 motion, then follow the arrow to Mecca. Works offline after calibration! 🧭"
    
    # Ramadan
    if intent == "ramadan":
        return "Enable Ramadan Mode for Suhoor/Iftar timings, special duas, and fasting reminders. May Allah bless your Ramadan and accept your fasts! 🌙"
    
    # Offline
    if "offline" in message_lower:
        return "SiratSync works offline for Quran, Hadith, Duas, Qibla, and Tasbih. Just download content once while online, then access anytime. Perfect for travel or areas with limited internet! 📴"
    
    # Learn Salah
    if "learn salah" in message_lower or "how to pray" in message_lower:
        return "Go to Learn Salah module for step-by-step guide with actions, words, and meanings. Perfect for beginners, new Muslims, or anyone wanting to improve their prayer! 🎯"
    
    # Community
    if "community" in message_lower:
        return "Join our peaceful Islamic community! Share reminders, follow others, and get inspiration. All content is moderated for safety and proper Islamic etiquette. 👥"
    
    # Features inquiry
    if intent == "app_features_inquiry" or "features" in message_lower or "what does it have" in message_lower:
        return get_features_response()
    
    return None


@app.get("/health")
@app.head("/health")
async def health():
    return {
        "status": "healthy",
        "version": "2.0",
        "timestamp": datetime.now().isoformat(),
        "components": {
            "intent_detector": "loaded",
            "rag_knowledge": f"loaded ({len(rag.list_categories())} categories)",
            "memory_manager": f"active ({len(memory.sessions)} active sessions)",
            "llm": "connected" if llm else "error"
        },
        "uptime": "online"
    }


@app.get("/user/{user_id}/summary")
async def get_user_summary(user_id: str):
    """Get a summary of user's session and profile"""
    try:
        profile = memory.get_user_profile(user_id)
        session_summary = memory.get_session_summary(user_id)
        
        return {
            "user_id": user_id,
            "profile": profile,
            "session": session_summary,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/user/{user_id}/session")
async def clear_user_session(user_id: str):
    """Clear user session data (privacy feature)"""
    try:
        result = memory.clear_session(user_id)
        return {"status": "success", "message": f"Session cleared for user {user_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting SiratSync AI Assistant Server v2.0")
    print("📍 Server will run on http://0.0.0.0:8000")
    print("📚 Documentation available at http://0.0.0.0:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
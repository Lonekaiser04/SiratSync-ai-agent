# SiratSync AI Backend 🕌

An Islamic lifestyle AI assistant backend for the **SiratSync** app — helping Muslims stay consistent in Salah, Quran, Dhikr, and daily habits.

---

## Tech Stack

- **FastAPI** — REST API framework
- **Groq (LLaMA 3.1 8B Instant)** — LLM for conversational responses
- **RAG** — JSON knowledge base for Islamic content & app features
- **Upstash Redis** — Persistent conversation memory & session management
- **Firebase Firestore** — User data storage
- **Pydantic v2** — Request/response validation

---

## Project Structure

```
chatbotbackend/
├── app/
│   ├── api/
│   │   ├── chat.py              # POST /chat — main chat endpoint
│   │   ├── health.py            # GET /health — health check
│   │   ├── summarize.py         # POST /summarize — post summarization
│   │   └── user.py              # GET/DELETE /user/{id} — session management
│   ├── core/
│   │   ├── config.py            # Centralized env config & constants
│   │   ├── logging.py           # Logging setup
│   │   └── security.py         # Security utilities
│   ├── data/
│   │   ├── knowledge.json       # Islamic content knowledge base
│   │   └── quran_indexed_final.json  # Full Quran with translations
│   ├── middleware/
│   │   ├── rate_limit.py        # Per-user rate limiting (60 req/min)
│   │   └── request_logger.py    # Request/response logging middleware
│   ├── models/
│   │   ├── request_models.py    # ChatRequest, SummarizeRequest (Pydantic)
│   │   └── response_models.py   # ChatResponse, SummarizeResponse (Pydantic)
│   ├── prompts/
│   │   ├── system_prompt.py     # LLM system prompt template
│   │   └── summarize_prompt.py  # Community post summarization prompt
│   ├── services/
│   │   ├── action_service.py    # Action suggestions & motivational quotes
│   │   ├── intent_service.py    # Rule-based intent & sentiment detection
│   │   ├── llm_service.py       # Groq LLM client & RAG formatting
│   │   ├── memory_service.py    # Redis-backed session & user profiling
│   │   └── rag_service.py       # Knowledge base retrieval (RAG)
│   ├── utils/
│   │   ├── cache.py             # In-memory response cache (TTL-based)
│   │   ├── helpers.py           # Quick replies & feature responses
│   │   └── validators.py        # Input validation utilities
│   └── main.py                  # FastAPI app entry point
├── scripts/
│   ├── cleanup_memory.py        # Purge inactive Redis sessions
│   ├── generate_metadata.py     # Data preprocessing utilities
│   └── keep_alive.py            # Render.com spin-down prevention
├── tests/
│   ├── test_all.py
│   ├── test_chat.py
│   ├── test_quran.py
│   └── test_rag.py
├── .render-build.sh             # Render.com build script
├── requirements.txt
└── README.md
```

---

## Setup

**1. Clone & install dependencies**
```bash
git clone <repo-url>
cd chatbotbackend
pip install -r requirements.txt
```

**2. Create a `.env` file**
```env
GROQ_API_KEY=your_groq_api_key_here

REDIS_URL=rediss://default:<password>@<host>:6379
# OR use individual Upstash vars:
UPSTASH_REDIS_HOST=your-host.upstash.io
UPSTASH_REDIS_PORT=6379
UPSTASH_REDIS_PASSWORD=your_password

FIREBASE_CREDENTIALS_JSON={"type":"service_account",...}

ALLOWED_ORIGINS=http://localhost:3000,https://yourdomain.com
RATE_LIMIT_MAX=60
ENV=production
RENDER_URL=https://your-app.onrender.com
```

**3. Run the server**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/chat` | Main chat endpoint |
| `POST` | `/summarize` | Summarize a community post |
| `GET` | `/health` | Server health check |
| `HEAD` | `/health` | Health check (lightweight) |
| `GET` | `/user/{user_id}/summary` | User session profile & consistency stats |
| `DELETE` | `/user/{user_id}/session` | Clear user session from Redis |

### Chat Request
```json
{
  "user_id": "user123",
  "message": "How do I track my prayers?",
  "user_name": "Ahmad",
  "app_version": "2.0",
  "context": "(optional) prior conversation string"
}
```

**Validation:** `message` max 2000 chars, `user_id` max 128 chars, `context` truncated at 4000 chars.

### Chat Response
```json
{
  "reply": "...",
  "intent": "salah",
  "sub_intent": "learn_more",
  "sentiment": "neutral",
  "actions": {
    "reminders": [],
    "habits": [],
    "duas": [],
    "quick_actions": []
  },
  "suggestions": ["🕌 Prayer Times", "⭐ Habits", "📖 Quran", "📿 Dhikr"],
  "motivational_quote": "...",
  "timestamp": "2025-01-01T12:00:00.000000"
}
```

### Summarize Request
```json
{
  "user_id": "user123",
  "post_content": "Long community post text here..."
}
```

### Summarize Response
```json
{
  "summary": "Condensed version of the post.",
  "original_length": 480,
  "summary_length": 95
}
```

### Health Response
```json
{
  "status": "healthy",
  "version": "2.0",
  "timestamp": "...",
  "components": {
    "intent_detector": "loaded",
    "rag_knowledge": "loaded (12 categories)",
    "memory_manager": "active (5 sessions)",
    "llm": "connected"
  },
  "uptime": "online"
}
```

---

## How It Works

1. **Cache Check** — Common, non-personalized queries are served instantly from in-memory cache (60 min TTL) without hitting the LLM.
2. **Intent Detection** — Classifies the message into primary intent (salah, quran, habit, struggling, etc.) and sub-intent, with sentiment and urgency scoring.
3. **RAG Retrieval** — Fetches the top-5 relevant chunks from the Islamic knowledge base and Quran index.
4. **User Profiling** — Loads consistency profile (struggling / medium / high) from Redis based on message history patterns.
5. **Quick Replies** — High-frequency intents (prayer times, features, greetings) are resolved with pre-built responses without the LLM.
6. **LLM Generation** — Groq (LLaMA 3.1 8B) generates a personalized response using the system prompt, RAG knowledge, conversation context, and user profile. Temperature and token limits adapt to intent and urgency.
7. **Action Suggestions** — Returns relevant app actions (open Habit Tracker, Quran, Qibla, etc.) and up to 4 quick-reply suggestions.
8. **Memory Store** — Both the user message and assistant reply are stored in Redis (last 50 messages per user, 60-day TTL via pipeline for efficiency).

---

## Features Covered

- 🕌 Prayer times & Adhan notifications
- 📖 Quran with English, Kashmiri & Urdu translations
- 📚 Sahih Bukhari & Muslim Hadith
- 📿 Duas, Adhkar & Tasbih counter
- ⭐ Ibadah Habit Tracker with streaks
- 🧭 Qibla Finder
- 🌙 Ramadan Mode
- 👥 Islamic Community (with post summarization)
- 🎯 Learn Salah & Shahadat guide

---

## Deployment (Render.com)

The `.render-build.sh` script handles build automatically:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Set the following in your Render environment variables (do **not** commit `.env` to Git):
- `GROQ_API_KEY`
- `REDIS_URL`
- `FIREBASE_CREDENTIALS_JSON`
- `RENDER_URL` (your Render service URL, used by keep-alive pinger)
- `RENDER=true` (triggers keep-alive on startup)

The `scripts/keep_alive.py` pings `/health` every 10 minutes to prevent the free-tier service from spinning down.

---

## Running Tests

```bash
pytest tests/
```

Test files cover: chat endpoint, Quran retrieval, RAG pipeline, and full integration (`test_all.py`).

---

## Developer

Built by **Kaiser Mohiuddin** — CS student & founder of SiratSync.
📧 lonekaiser04@gmail.com
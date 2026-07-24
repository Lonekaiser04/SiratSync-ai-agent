# SiratSync AI Backend

An Islamic lifestyle AI assistant backend for the **SiratSync** app — helping Muslims stay consistent in Salah, Quran, Dhikr, and daily habits.

**🌐 Website:** [siratsync.in](https://siratsync.in) &nbsp;|&nbsp; **📱 Android:** [Get it on Google Play](https://play.google.com/store/apps/details?id=com.islamic.streakly) &nbsp;|&nbsp; **💬 WhatsApp:** [Chat with Sirat Assistant](https://wa.me/919541871382)

---

## Screenshots

This backend powers Sirat Assistant across the SiratSync app and WhatsApp.

<table>
  <tr>
    <td width="33%">
      <img src="screenshots/salah-consistency.jpeg" alt="Sirat Assistant answering a question about staying consistent in Salah" width="100%">
      <p align="center"><em>In-app guidance, grounded in app features</em></p>
    </td>
    <td width="33%">
      <img src="screenshots/verse-lookup.jpeg" alt="Direct verse lookup showing Arabic, English, transliteration, and Urdu" width="100%">
      <p align="center"><em>Direct verse lookup (94:5) — Arabic, English, transliteration & Urdu</em></p>
    </td>
    <td width="33%">
      <img src="screenshots/surah-info-query.jpeg" alt="Surah-level query returning statistics and notable verses" width="100%">
      <p align="center"><em>Surah-level queries with stats & notable verses</em></p>
    </td>
  </tr>
  <tr>
    <td width="33%">
      <img src="screenshots/community-feature.jpeg" alt="WhatsApp conversation explaining the Community feature" width="100%">
      <p align="center"><em>Explaining app features conversationally (via WhatsApp)</em></p>
    </td>
    <td width="33%">
      <img src="screenshots/post-summarization.jpeg" alt="AI-generated summary of a community post" width="100%">
      <p align="center"><em>AI post summarization in the Community feed</em></p>
    </td>
    <td width="33%">
      <img src="screenshots/whatsapp-verse-lookup.jpeg" alt="WhatsApp verse lookup with similar verses shown" width="100%">
      <p align="center"><em>WhatsApp: verse lookup with similar-ayah suggestions</em></p>
    </td>
  </tr>
</table>

---

## Tech Stack

- **FastAPI** — REST API framework
- **Groq (LLaMA 3.1 8B Instant)**, called via the async client — LLM for conversational responses
- **RAG** — JSON knowledge base + full Quran index for Islamic content & app features (no vector DB; retrieval is regex/keyword-based, see [RAG Retrieval](#rag-retrieval) below)
- **Redis** (Upstash or any standard Redis) — conversation memory, response cache, and rate limiting. Falls back to an in-process, single-worker store automatically if unconfigured (fine for local dev, **not** recommended for production)
- **Pydantic v2** — request/response validation

---

## Project Structure

```
chatbotbackend/
├── app/
│   ├── api/
│   │   ├── chat.py              # POST /chat — main chat endpoint
│   │   ├── health.py            # GET /health — health check (pings Groq for real)
│   │   ├── summarize.py         # POST /summarize — post summarization
│   │   ├── user.py              # GET/DELETE /user/{id} — session management (auth-protected)
│   │   └── whatsapp.py          # WhatsApp Cloud API webhook
│   ├── core/
│   │   ├── config.py            # Centralized, validated env config (Settings class)
│   │   └── security.py          # Internal API-key auth dependency + prompt-injection guards
│   ├── data/
│   │   ├── knowledge.json       # Islamic content / app-feature knowledge base
│   │   └── quran_indexed_final.json  # Full Quran (114 surahs) with translations & metadata
│   ├── middleware/
│   │   ├── rate_limit.py        # Redis sliding-window rate limiting (60 req/min default), in-process fallback
│   │   └── request_logger.py    # Request/response logging with correlation IDs
│   ├── models/
│   │   ├── request_models.py    # ChatRequest, SummarizeRequest (Pydantic v2)
│   │   └── response_models.py   # ChatResponse, SummarizeResponse, typed ActionsPayload
│   ├── prompts/
│   │   ├── system_prompt.py     # LLM system prompt template
│   │   └── summarize_prompt.py  # Community post summarization prompt
│   ├── services/
│   │   ├── action_service.py    # Action suggestions & motivational quotes (timezone-aware)
│   │   ├── intent_service.py    # Rule-based intent & sentiment detection
│   │   ├── memory_service.py    # Redis-backed session & user profiling
│   │   └── rag_service.py       # Knowledge base + Quran retrieval (RAG)
│   ├── utils/
│   │   ├── cache.py             # Response cache — Redis-backed when available, local TTL fallback
│   │   └── helpers.py           # Quick replies, feature responses, RAG-grounded LLM calls
│   └── main.py                  # FastAPI app entry point (Quran index preloaded at startup)
├── scripts/
│   ├── cleanup_memory.py        # Purge inactive Redis sessions — run on a schedule (not automatic)
│   ├── generate_metadata.py     # Offline Quran metadata preprocessing (not part of the running app)
│   └── keep_alive.py            # Render.com spin-down prevention (opt-in via env var)
├── tests/                       # Add/restore your test suite here (see Testing section)
├── .render-build.sh             # Render.com build script
├── .env.example                 # Template for local .env — copy and fill in
├── requirements.txt
├── LICENSE
└── readme.md
```

---

## Setup

**1. Clone & install dependencies**
```bash
git clone https://github.com/lonekaiser04/siratsync-ai-backend.git
cd chatbotbackend
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**2. Create your `.env` file**
```bash
cp .env.example .env
```
Then fill in at minimum:
```env
GROQ_API_KEY=your_groq_api_key_here

# Generate your own value for this — see "Authentication" below.
INTERNAL_API_KEY=

# Optional but recommended for anything beyond local single-process testing:
REDIS_URL=rediss://default:<password>@<host>:6379
# OR:
UPSTASH_REDIS_HOST=your-host.upstash.io
UPSTASH_REDIS_PORT=6379
UPSTASH_REDIS_PASSWORD=your_password

ALLOWED_ORIGINS=http://localhost:3000,https://yourdomain.com
ENV=development
```
See `.env.example` for the full list of optional settings (LLM tuning, rate limits, cache TTLs, WhatsApp config).

**3. Run the server**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**4. Verify it's working**

Visit `http://127.0.0.1:8000/docs` for the interactive API explorer, or check `http://127.0.0.1:8000/health` — a healthy response looks like:
```json
{"status": "healthy", "components": {"llm": "connected", ...}}
```
If `llm` shows `"error"`, double-check `GROQ_API_KEY`.

---

## Authentication

The `/user/{user_id}/summary` and `/user/{user_id}/session` endpoints expose per-user data and require an `X-API-Key` header matching `INTERNAL_API_KEY` from your `.env`.

Generate a key yourself (this is not issued by any external service — you create it):
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
Put the result in `.env` as `INTERNAL_API_KEY=...`, restart the server, and pass it as a header on protected requests:
```bash
curl -H "X-API-Key: your_generated_key" http://127.0.0.1:8000/user/some_user/summary
```
If `INTERNAL_API_KEY` is left unset, a random key is generated per-process at startup (logged as a warning) — fine for a quick local test, but it changes on every restart, so set it explicitly for anything persistent, and always in production.

---

## API Endpoints

| Method | Endpoint | Auth required | Description |
|--------|----------|:---:|-------------|
| `POST` | `/chat` | No | Main chat endpoint |
| `POST` | `/summarize` | No | Summarize a community post |
| `GET` / `HEAD` | `/health` | No | Server health check (includes a real Groq connectivity check) |
| `GET` | `/user/{user_id}/summary` | **Yes** | User session profile & consistency stats |
| `DELETE` | `/user/{user_id}/session` | **Yes** | Clear user session from Redis |
| `GET` / `POST` | `/webhook/whatsapp` | Signed (Meta HMAC) | WhatsApp Cloud API webhook |

### Chat Request
```json
{
  "user_id": "user123",
  "message": "How do I track my prayers?",
  "user_name": "Ahmad",
  "app_version": "2.0",
  "context": "(optional) prior conversation string",
  "user_timezone": "Asia/Karachi"
}
```

**Validation:** `message` max 2000 chars (empty rejected), `user_id` max 128 chars, `context` truncated at 4000 chars, `user_timezone` must be a valid IANA name (e.g. `Asia/Karachi`) or is ignored. `user_timezone` drives time-of-day suggestions (morning/evening adhkar); if omitted, these default to UTC rather than the server's local time.

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
    "resources": [],
    "encouragement": "",
    "quick_actions": []
  },
  "suggestions": ["🕌 Prayer Times", "⭐ Habits", "📖 Quran", "📿 Dhikr"],
  "motivational_quote": "...",
  "timestamp": "2026-01-01T12:00:00.000000",
  "sources": [
    {"type": "quran", "label": "Sahih International", "detail": "English Translation"}
  ]
}
```

### Summarize Request / Response

Unchanged from before:
```json
{"user_id": "user123", "post_content": "Long community post text here..."}
```
```json
{"summary": "Condensed version of the post.", "original_length": 480, "summary_length": 95}
```

### Health Response
```json
{
  "status": "healthy",
  "version": "2.0",
  "timestamp": "...",
  "components": {
    "intent_detector": "loaded",
    "rag_knowledge": "loaded (32 categories)",
    "memory_manager": {
      "status": "active",
      "backend": "redis",
      "sessions": {"redis_sessions": 24, "fallback_sessions": 0}
    },
    "llm": "connected"
  },
  "uptime": "online"
}
```
`llm` reflects a real (short, cached ~60s) request to Groq — `"error"` means Groq is actually unreachable or the API key is invalid, not just that the client object exists.

---

## How It Works

1. **Cache Check** — Common, non-personalized queries are served instantly from cache (Redis-backed when available, so this stays correct across multiple workers/instances; falls back to an in-process TTL cache otherwise) without hitting the LLM.
2. **Intent Detection** — Classifies the message into a primary intent (salah, quran, habit, struggling, etc.) and sub-intent, with sentiment and urgency scoring.
3. **RAG Retrieval** — Fetches relevant content from the Islamic knowledge base and Quran index, scoped per `user_id` so follow-up questions ("show me verse 5 of it") resolve against *that user's* recent context, not another user's.
4. **User Profiling** — Loads a consistency profile (struggling / medium / high) from Redis based on message history patterns.
5. **Quick Replies** — High-frequency intents (prayer times, features, greetings, direct verse/surah lookups) are resolved without the LLM.
6. **LLM Generation** — Groq (LLaMA 3.1 8B), called asynchronously, generates a personalized response using the system prompt, RAG knowledge, conversation context, and user profile. Temperature and token limits adapt to intent and urgency. User-supplied text is sanitized and screened for common prompt-injection patterns first.
7. **Action Suggestions** — Returns relevant app actions (open Habit Tracker, Quran, Qibla, etc.) and up to 4 quick-reply suggestions. Time-of-day suggestions use `user_timezone` if provided.
8. **Memory Store** — Both the user message and assistant reply are stored in Redis (last 50 messages per user, 60-day TTL, written via a single pipelined round trip).

### RAG Retrieval

Retrieval is currently regex/keyword-based against a hand-curated knowledge base and the full Quran index — there is no embedding/vector search layer. This works well for known topics and direct verse/surah references, but won't generalize to phrasings that don't share keywords with the curated topic list. If you're extending this, adding a semantic search layer (e.g. sentence-transformers + a small vector index over the existing verse/knowledge-base text) is the highest-leverage improvement to retrieval quality.

### A note on Hadith content

The app references Sahih al-Bukhari and Sahih Muslim in its prompts and UI copy, but **no hadith corpus is bundled in this repository** — only a handful of hardcoded motivational quotes with informal attributions (no hadith number or chain). If hadith accuracy matters for your use case, source a verified, numbered hadith dataset before relying on these for anything where authenticity is important.

---

## Features Covered

- 🕌 Prayer times & Adhan notifications
- 📖 Quran with English, Kashmiri & Urdu translations
- 📚 Sahih Bukhari & Muslim Hadith *(UI/prompt references only — see note above)*
- 📿 Duas, Adhkar & Tasbih counter
- ⭐ Ibadah Habit Tracker with streaks
- 🧭 Qibla Finder
- 🌙 Ramadan Mode
- 👥 Islamic Community (with post summarization)
- 🎯 Learn Salah & Shahadat guide
- 💬 WhatsApp integration via Meta Cloud API webhook

---

## Deployment (Render.com)

The `.render-build.sh` script handles the build:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Set the following in your Render environment variables (do **not** commit `.env` to Git):
- `GROQ_API_KEY` — required
- `INTERNAL_API_KEY` — required; generate your own, see [Authentication](#authentication). Set this explicitly so it doesn't regenerate (and invalidate itself) on every deploy/restart.
- `REDIS_URL` (or `UPSTASH_REDIS_HOST` / `UPSTASH_REDIS_PORT` / `UPSTASH_REDIS_PASSWORD`) — strongly recommended in production; without it, rate limiting/caching/memory fall back to a single-process in-memory store, which breaks down as soon as you run more than one worker or instance
- `ALLOWED_ORIGINS` — your real frontend domain(s)
- `ENV=production`
- `RENDER_URL` — your Render service's own URL, used by the keep-alive pinger
- `RENDER=true` (or `KEEP_ALIVE=true`) — enables the keep-alive pinger on startup

**Before your first deploy:** set env vars in the Render dashboard, deploy once manually to confirm `/health` looks correct, then enable auto-deploy if you want push-to-deploy going forward. Render keeps deploy history under the service's "Events"/"Deploys" tab, so you can roll back to a previous deploy with one click if something's wrong.

The `scripts/keep_alive.py` pings `/health` every 10 minutes to prevent the free-tier service from spinning down.

---

## Maintenance

Redis session data is **not** cleaned up automatically. Run periodically (cron / Render Cron Job):
```bash
python -m scripts.cleanup_memory --inactive-days 60
```

---

## Running Tests

A `tests/` folder is scaffolded for your own test suite. A basic end-to-end smoke test (hits a running server over HTTP and checks the core endpoints, auth, validation, and per-user context isolation) is available separately — point it at your running instance:
```bash
python test_backend.py --api-key YOUR_INTERNAL_API_KEY
```
If you maintain a pytest-based suite under `tests/`, make sure your virtual environment has all of `requirements.txt` installed (`ModuleNotFoundError: No module named 'redis'` usually means you're running from a different environment than the one you installed dependencies into).

```bash
pytest tests/
```

---

## License

All Rights Reserved.

Copyright (c) 2026 Kaiser Mohiuddin / SiratSync

This repository is proprietary software shared for portfolio and viewing purposes only.
Unauthorized copying, modification, distribution, or commercial use is strictly prohibited without explicit written permission.

---

## Developer

Built by **Kaiser Mohiuddin** — CS student & founder of SiratSync.

- Website: [siratsync.in](https://siratsync.in)
- Android app: [Google Play](https://play.google.com/store/apps/details?id=com.islamic.streakly)
- WhatsApp: [wa.me/919541871382](https://wa.me/919541871382)

For professional inquiries, connect via LinkedIn or official Website.
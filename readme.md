# SiratSync AI Backend 🕌

An Islamic lifestyle AI assistant backend for the **SiratSync** app — helping Muslims stay consistent in Salah, Quran, Dhikr, and daily habits.

---

## Tech Stack

- **FastAPI** — REST API framework
- **Groq (LLaMA 3.1 8B)** — LLM for conversational responses
- **RAG** — JSON knowledge base for Islamic content & app features
- **In-memory sessions** — Conversation history & user profiling

---

## Project Structure

```
├── main.py              # FastAPI app, chat endpoint, prompt logic
├── intent_detector.py   # Rule-based intent & sentiment detection
├── rag_knowledge.py     # Knowledge base retrieval (RAG)
├── memory_manager.py    # Session management & user profiling
├── actions.py           # Action suggestions & motivational quotes
├── knowledge.json       # Islamic content knowledge base
└── requirements.txt
```

---

## Setup

**1. Clone & install dependencies**
```bash
pip install -r requirements.txt
```

**2. Create a `.env` file**
```env
GROQ_API_KEY=your_groq_api_key_here
```

**3. Run the server**
```bash
python main.py
# Server starts at http://0.0.0.0:8000
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/chat` | Main chat endpoint |
| `GET` | `/health` | Server health check |
| `GET` | `/user/{user_id}/summary` | User session profile |
| `DELETE` | `/user/{user_id}/session` | Clear user session |

### Chat Request
```json
{
  "user_id": "user123",
  "message": "How do I track my prayers?",
  "user_name": "Ahmad"
}
```

### Chat Response
```json
{
  "reply": "...",
  "intent": "salah",
  "sentiment": "neutral",
  "actions": { "habits": [], "duas": [], "quick_actions": [] },
  "suggestions": ["🕌 Prayer Times", "⭐ Habits"],
  "motivational_quote": "...",
  "timestamp": "..."
}
```

---

## Complete Architecture & How the Agent Works

### 1) High-Level System Architecture

```
Client App (Flutter/Web)
        │
        ▼
FastAPI Server (`main.py`)
  ├─ Middleware: CORS, request logging, rate limiting
  ├─ `/chat` orchestration pipeline
  ├─ `/health`, `/user/{id}/summary`, `/user/{id}/session`
  │
  ├─ Intent Engine (`intent_detector.py`)
  ├─ Retrieval Engine (`rag_knowledge.py` + `knowledge.json`)
  ├─ Session Memory (`memory_manager.py`)
  ├─ Response Cache (`cache.py`)
  ├─ Action/Suggestion Engine (`actions.py`)
  └─ LLM Gateway (Groq `llama-3.1-8b-instant`)
```

### 2) Runtime Request Flow (`POST /chat`)

For each user message, the backend runs this pipeline:

1. **Cache lookup first**  
   Checks normalized message in in-memory cache (`ResponseCache`) for instant reuse of non-personalized responses.

2. **Persist user message**  
   Stores message in `MemoryManager` session history (`user_id` scoped).

3. **Context building**  
   Builds short conversation context from recent messages (or uses client-provided context when sent).

4. **Intent + sentiment + urgency detection**  
   `IntentDetector.detect()` classifies:
   - primary intent (e.g., `salah`, `quran`, `struggling`, `technical`)
   - sub-intent (finer routing)
   - sentiment (positive/negative/neutral/concerned)
   - urgency level

5. **Follow-up override logic**  
   For short confirmations like “yes”, the server uses last question/context to re-map intent correctly.

6. **Knowledge retrieval (RAG)**  
   `RAGKnowledge.retrieve()` fetches top relevant chunks from `knowledge.json` with:
   - direct-answer shortcuts
   - FAQ shortcuts
   - keyword/category scoring

7. **User profile extraction**  
   `MemoryManager.get_user_profile()` computes consistency level, struggles, achievements, topics, and advice.

8. **Quick-response path (LLM bypass)**  
   `get_quick_response()` handles common intents/patterns instantly (greeting, features, prayer-time setup, etc.).

9. **LLM path (fallback when needed)**  
   If no quick response:
   - builds dynamic prompt (context + profile + RAG knowledge + question)
   - calls Groq chat completion (`llama-3.1-8b-instant`)
   - tunes temperature and max tokens based on intent/urgency

10. **Action generation for app UI**  
    `suggest_actions()` returns practical next steps:
    reminders, habits, duas, quick actions, encouragement.

11. **UI quick-reply chips**  
    `get_quick_reply_suggestions()` returns 4 context-aware suggestion buttons.

12. **Motivational quote selection**  
    Picks quote according to consistency/struggle state.

13. **Persist assistant response**  
    Adds assistant reply to memory for future personalization.

14. **Cache response**  
    Caches safe/common responses with TTL (skips personal prompts).

15. **Return structured response**  
    Sends `ChatResponse` JSON: reply, intent, sentiment, actions, suggestions, quote, timestamp.

### 3) Key Components and Responsibilities

- **`main.py`**: API surface + orchestration logic for every chat turn.
- **`intent_detector.py`**: Regex-based multi-intent scoring + sub-intent derivation.
- **`rag_knowledge.py`**: Local JSON knowledge retrieval with scoring and direct-answer fast paths.
- **`memory_manager.py`**: In-memory conversation sessions and lightweight user profiling.
- **`cache.py`**: In-memory TTL response cache to reduce repeated LLM calls and latency.
- **`actions.py`**: Action recommendations, motivational quotes, and quick-reply suggestions.
- **`knowledge.json`**: Domain content (features, Islamic guidance, FAQs, troubleshooting, etc.).
- **`keep_alive.py`**: Optional Render keep-alive ping thread for hosted deployments.

### 4) API Architecture

- **`POST /chat`**: Main intelligence pipeline (all components integrated).
- **`GET /health`**: Runtime status and loaded component info.
- **`GET /user/{user_id}/summary`**: Session/profile summary for diagnostics or UI.
- **`DELETE /user/{user_id}/session`**: Privacy endpoint to clear user session state.

### 5) State, Personalization, and Safety Controls

- **State model**: In-memory dictionaries (no persistent DB in this repo).
- **Personalization**: Per-user session context + derived consistency profile.
- **Rate limiting**: In-memory per-user/IP limiter in middleware.
- **Error handling**: Graceful fallback message from `/chat` on runtime exceptions.
- **Safety boundaries**: Prompt-level constraints for tone and scope (non-medical/legal/extreme rulings).

### 6) Operational Notes

- Requires `GROQ_API_KEY` at startup.
- RAG is local-file based (`knowledge.json`) and loaded at service start.
- Designed for low-latency responses via:
  - quick-reply bypass,
  - cache hits,
  - lightweight intent detection.
- Session and cache reset on process restart (because they are in-memory).

---

## Features Covered

- 🕌 Prayer times & Adhan notifications
- 📖 Quran with English, Kashmiri & Urdu translations
- 📚 Sahih Bukhari & Muslim Hadith
- 📿 Duas, Adhkar & Tasbih counter
- ⭐ Ibadah Habit Tracker with streaks
- 🧭 Qibla Finder
- 🌙 Ramadan Mode
- 👥 Islamic Community
- 🎯 Learn Salah & Shahadat guide

---

## Developer

Built by **Kaiser Mohiuddin** — CS student & founder of SiratSync.
📧 lonekaiser04@gmail.com

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

## How It Works

1. **Intent Detection** — Classifies the message (salah, quran, habit, struggling, etc.)
2. **RAG Retrieval** — Fetches relevant Islamic knowledge or app feature info
3. **User Profiling** — Tracks consistency level (struggling / medium / high) across the session
4. **Quick Replies** — Common queries are answered instantly without hitting the LLM
5. **LLM Generation** — Groq generates a personalized response using context + knowledge

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
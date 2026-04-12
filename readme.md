# SiratSync API

Islamic Lifestyle Assistant API with AI-powered guidance for Salah, Quran, Hadith, and habit tracking.

## Features
- 🤖 AI-powered Islamic assistant using Groq's LLaMA
- 🎯 Intent detection for Islamic queries
- 📚 RAG knowledge base with Quran, Hadith, Duas
- 💾 User memory and context management
- ⚡ Action suggestions for habits and reminders

## API Endpoints
- `POST /chat` - Main chat endpoint
- `GET /health` - Health check
- `GET /user/{user_id}/summary` - User session summary
- `DELETE /user/{user_id}/session` - Clear user data

## Environment Variables
- `GROQ_API_KEY` - Your Groq API key (required)

## Deployment
This API is deployed on Render.com. See `render.yaml` for configuration.
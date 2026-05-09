import os
from dotenv import load_dotenv

load_dotenv()

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:5173,https://siratsync-ai-agent.onrender.com,https://siratsync.in"
    ).split(",")
]

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

RATE_LIMIT_MAX_KEYS = 10_000
RATE_LIMIT_RPM = 60

SUMMARY_CACHE_PREFIX = "summarize:"
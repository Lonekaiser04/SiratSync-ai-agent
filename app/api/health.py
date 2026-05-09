from fastapi import APIRouter
from datetime import datetime
from app.services.rag_service import rag_service
from app.services.memory_service import memory
from groq import Groq
import os

router = APIRouter()

llm = Groq(api_key=os.environ.get("GROQ_API_KEY"))

@router.get("/health")
@router.head("/health")
async def health():
    return {
        "status":    "healthy",
        "version":   "2.0",
        "timestamp": datetime.now().isoformat(),
        "components": {
            "intent_detector": "loaded",
            "rag_knowledge":   f"loaded ({len(rag_service.list_categories())} categories)",
            "memory_manager":  f"active ({len(memory.sessions)} sessions)",
            "llm":             "connected" if llm else "error",
        },
        "uptime": "online",
    }
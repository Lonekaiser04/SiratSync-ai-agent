import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
from dotenv import load_dotenv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.middleware.rate_limit import rate_limit_middleware
from app.middleware.request_logger import log_requests_middleware
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.user import router as user_router
from app.api.summarize import router as summarize_router
from app.core.config import ALLOWED_ORIGINS

load_dotenv()

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="SiratSync AI Assistant API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

app.middleware("http")(rate_limit_middleware)
app.middleware("http")(log_requests_middleware)

app.include_router(chat_router)
app.include_router(health_router)
app.include_router(user_router)
app.include_router(summarize_router)

@app.on_event("startup")
async def startup_event():
    from app.services.rag_service import rag_service
    if not os.environ.get("GROQ_API_KEY"):
        raise ValueError("GROQ_API_KEY is required")
    logging.getLogger(__name__).info("✅ SiratSync API started successfully")
    if os.environ.get("RENDER") or os.environ.get("KEEP_ALIVE"):
        try:
            from scripts.keep_alive import keep_render_alive
            keep_render_alive()
        except ImportError:
            logging.getLogger(__name__).warning("⚠️ keep_alive module not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
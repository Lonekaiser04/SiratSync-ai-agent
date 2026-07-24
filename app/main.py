"""
FastAPI application entry point.

Startup sequence:
  1. Validate required settings (fail fast if GROQ_API_KEY is missing).
  2. Eagerly load the Quran index so the first real user request doesn't
     pay the ~20MB JSON parse cost synchronously (previously this was
     lazy-loaded on first use inside an `async def` handler, which could
     stall the event loop for whichever user happened to trigger it).
  3. Optionally start the Render keep-alive pinger.

Middleware ordering: `request_logger` is registered last so it wraps
everything (including rate limiting) and can tag every response — including
429s — with a correlation ID and log line.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.summarize import router as summarize_router
from app.api.user import router as user_router
from app.api.whatsapp import router as whatsapp_router
from app.core.config import settings
from app.middleware.rate_limit import rate_limit_middleware
from app.middleware.request_logger import log_requests_middleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate()

    # Preload the Quran index at startup rather than on first user request.
    try:
        from app.services.rag_service import rag_service

        rag_service._load_quran_data()
        logger.info("✅ Quran index preloaded at startup")
    except Exception as e:
        # Don't crash the whole app over a data-loading issue; RAG calls
        # will retry loading lazily and log their own errors if it's fatal.
        logger.error("⚠️ Failed to preload Quran index at startup: %s", e, exc_info=True)

    logger.info("✅ SiratSync API started successfully")

    if settings.KEEP_ALIVE_ENABLED:
        try:
            from scripts.keep_alive import keep_render_alive

            keep_render_alive()
        except ImportError:
            logger.warning("⚠️ keep_alive module not found")

    yield

    logger.info("👋 SiratSync API shutting down")


app = FastAPI(title="SiratSync AI Assistant API", version="2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*", "X-API-Key", "X-Request-ID", "X-User-ID"],
)

app.middleware("http")(rate_limit_middleware)
app.middleware("http")(log_requests_middleware)

app.include_router(chat_router)
app.include_router(health_router)
app.include_router(user_router)
app.include_router(summarize_router)
app.include_router(whatsapp_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

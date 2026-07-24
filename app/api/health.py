"""
Health check endpoint.

The LLM connectivity check performs a real (tiny) request against Groq
rather than just checking that the client object was constructed — a
constructed client is always truthy, so the previous implementation could
never detect an actual outage or revoked API key. The real check result is
cached briefly so frequent monitoring probes don't multiply LLM spend.
"""
import logging
import time
from datetime import datetime

from fastapi import APIRouter
from groq import AsyncGroq, GroqError

from app.core.config import settings
from app.services.memory_service import memory
from app.services.rag_service import rag_service

logger = logging.getLogger(__name__)

router = APIRouter()

_llm = AsyncGroq(api_key=settings.GROQ_API_KEY)

_LLM_CHECK_CACHE_SECONDS = 60
_last_llm_check_time: float = 0.0
_last_llm_check_result: str = "unknown"


async def _check_llm_connectivity() -> str:
    global _last_llm_check_time, _last_llm_check_result

    now = time.monotonic()
    if now - _last_llm_check_time < _LLM_CHECK_CACHE_SECONDS:
        return _last_llm_check_result

    if not settings.GROQ_API_KEY:
        _last_llm_check_result = "not_configured"
        _last_llm_check_time = now
        return _last_llm_check_result

    try:
        await _llm.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            timeout=5,
        )
        _last_llm_check_result = "connected"
    except GroqError as e:
        logger.warning("Health check: LLM connectivity failed: %s", e)
        _last_llm_check_result = "error"
    except Exception as e:  # network-level failures, timeouts, etc.
        logger.warning("Health check: unexpected LLM check failure: %s", e)
        _last_llm_check_result = "error"

    _last_llm_check_time = now
    return _last_llm_check_result


@router.get("/health")
@router.head("/health")
async def health():
    llm_status = await _check_llm_connectivity()
    session_counts = memory.sessions

    overall_status = "healthy" if llm_status in ("connected", "not_configured") else "degraded"

    return {
        "status": overall_status,
        "version": "2.0",
        "timestamp": datetime.now().isoformat(),
        "components": {
            "intent_detector": "loaded",
            "rag_knowledge": f"loaded ({len(rag_service.list_categories())} categories)",
            "memory_manager": {
                "status": "active",
                "backend": "redis" if memory._is_redis_available() else "in-memory-fallback",
                "sessions": session_counts,
            },
            "llm": llm_status,
        },
        "uptime": "online",
    }

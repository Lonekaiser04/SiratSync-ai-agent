"""
Health check endpoints:
  - /health/live: Ultra-lightweight liveness probe for uptime monitors and keep-alive pingers (no external dependencies, zero spend).
  - /health and /health/ready: Readiness and component diagnostics (RAG, Redis, LLM configuration).
"""
import logging
import time
from datetime import datetime

from fastapi import APIRouter, Query
from groq import AsyncGroq, GroqError, NotFoundError

from app.core.config import settings
from app.services.memory_service import memory
from app.services.rag_service import rag_service

logger = logging.getLogger(__name__)

router = APIRouter()

_llm = AsyncGroq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None

_LLM_CHECK_CACHE_SECONDS = 300  # 5 minutes cache for deep checks
_last_llm_check_time: float = 0.0
_last_llm_check_result: str = "unknown"


@router.get("/health/live")
@router.head("/health/live")
async def liveness():
    """Ultra-lightweight liveness probe for uptime monitors and keep-alive pingers."""
    return {
        "status": "alive",
        "version": "2.0",
        "timestamp": datetime.now().isoformat(),
    }


async def _check_llm_connectivity(deep: bool = False) -> str:
    global _last_llm_check_time, _last_llm_check_result

    if not settings.GROQ_API_KEY:
        return "not_configured"

    # For standard health checks, reporting configured is sufficient and avoids wasting LLM tokens
    if not deep:
        return "configured"

    now = time.monotonic()
    if now - _last_llm_check_time < _LLM_CHECK_CACHE_SECONDS and _last_llm_check_result != "unknown":
        return _last_llm_check_result

    try:
        if _llm is not None:
            model_to_test = settings.GROQ_MODEL
            try:
                await _llm.chat.completions.create(
                    model=model_to_test,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                    timeout=5,
                )
                _last_llm_check_result = "connected"
            except NotFoundError as nfe:
                if model_to_test != settings.FALLBACK_GROQ_MODEL:
                    logger.warning(
                        "Health check: Model %s not found (404). Testing fallback %s: %s",
                        model_to_test,
                        settings.FALLBACK_GROQ_MODEL,
                        nfe,
                    )
                    await _llm.chat.completions.create(
                        model=settings.FALLBACK_GROQ_MODEL,
                        messages=[{"role": "user", "content": "ping"}],
                        max_tokens=1,
                        timeout=5,
                    )
                    _last_llm_check_result = "connected_fallback"
                else:
                    raise
        else:
            _last_llm_check_result = "not_configured"
    except GroqError as e:
        logger.warning("Health check: LLM connectivity failed: %s", e)
        _last_llm_check_result = "error"
    except Exception as e:
        logger.warning("Health check: unexpected LLM check failure: %s", e)
        _last_llm_check_result = "error"

    _last_llm_check_time = now
    return _last_llm_check_result


@router.get("/health")
@router.head("/health")
@router.get("/health/ready")
async def health(deep: bool = Query(default=False, description="Run deep external LLM test")):
    llm_status = await _check_llm_connectivity(deep=deep)
    is_redis = await memory.is_redis_available()
    session_counts = await memory.get_session_counts()

    overall_status = "healthy" if llm_status in ("configured", "connected", "connected_fallback", "not_configured") else "degraded"

    return {
        "status": overall_status,
        "version": "2.0",
        "timestamp": datetime.now().isoformat(),
        "components": {
            "intent_detector": "loaded",
            "rag_knowledge": f"loaded ({len(rag_service.list_categories())} categories)",
            "memory_manager": {
                "status": "active",
                "backend": "redis" if is_redis else "in-memory-fallback",
                "sessions": session_counts,
            },
            "llm": llm_status,
            "model": settings.GROQ_MODEL,
            "fallback_model": settings.FALLBACK_GROQ_MODEL,
        },
        "uptime": "online",
    }

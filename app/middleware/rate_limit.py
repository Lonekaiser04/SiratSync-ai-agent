"""
Rate limiting middleware.

Primary implementation uses async Redis (sorted-set sliding window) so the limit
is enforced correctly across multiple worker processes without blocking the event loop.

Identifies clients securely via:
  1. Cryptographically verified Firebase auth token (Authorization: Bearer <token>)
  2. Internal API key (X-API-Key)
  3. Reverse-proxy-safe client IP (X-Forwarded-For leftmost public hop) + user ID
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.security import get_client_ip, verify_firebase_token

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60


class _LocalSlidingWindow:
    """Bounded in-process fallback limiter (per-worker)."""

    def __init__(self, max_keys: int) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._max_keys = max_keys

    def is_allowed(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        cutoff = now - _WINDOW_SECONDS

        if len(self._hits) > self._max_keys:
            logger.warning("Local rate-limit table exceeded %s keys — resetting", self._max_keys)
            self._hits.clear()

        bucket = self._hits[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            return False

        bucket.append(now)
        return True


_local_limiter = _LocalSlidingWindow(max_keys=settings.RATE_LIMIT_MAX_KEYS)


def _get_client_key(request: Request) -> str:
    # 1. Cryptographically verified Firebase ID token takes highest priority
    auth_header = request.headers.get("Authorization")
    verified_uid = verify_firebase_token(auth_header)
    if verified_uid:
        request.state.authenticated_user_id = verified_uid
        return f"user:{verified_uid}"

    # 2. Internal API key
    api_key = request.headers.get("X-API-Key")
    if api_key and api_key == settings.INTERNAL_API_KEY:
        return "internal:authorized"

    # 3. Client IP safely extracted from reverse proxy headers
    client_ip = get_client_ip(request)

    # 4. Optional user ID from header scoped under client IP to prevent spoofing
    user_id = request.headers.get("X-User-ID")
    if user_id:
        safe_uid = user_id.strip()[:64]
        return f"user:{safe_uid}:ip:{client_ip}"

    return f"ip:{client_ip}"


async def _redis_sliding_window_allowed(redis_client, key: str, limit: int) -> bool | None:
    """Non-blocking async sliding window using redis.asyncio."""
    try:
        now = time.time()
        cutoff = now - _WINDOW_SECONDS
        redis_key = f"ratelimit:{key}"

        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(redis_key, 0, cutoff)
            pipe.zcard(redis_key)
            pipe.zadd(redis_key, {str(now): now})
            pipe.expire(redis_key, _WINDOW_SECONDS + 5)
            _, current_count, _, _ = await pipe.execute()

        if current_count >= limit:
            await redis_client.zrem(redis_key, str(now))
            return False
        return True
    except Exception as e:
        logger.warning("Redis rate limiter unavailable (%s) — using local fallback", e)
        return None


async def rate_limit_middleware(request: Request, call_next):
    # Health and docs endpoints stay exempt
    if request.url.path in {"/health", "/health/live", "/health/ready", "/docs", "/openapi.json", "/redoc"}:
        return await call_next(request)

    client_key = _get_client_key(request)
    if client_key == "internal:authorized":
        return await call_next(request)

    redis_client = None
    try:
        from app.services.memory_service import memory as _memory

        if await _memory.is_redis_available():
            redis_client = _memory.redis
    except Exception:
        redis_client = None

    allowed: bool | None = None
    if redis_client is not None:
        allowed = await _redis_sliding_window_allowed(redis_client, client_key, settings.RATE_LIMIT_RPM)

    if allowed is None:
        allowed = _local_limiter.is_allowed(client_key, settings.RATE_LIMIT_RPM)

    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please wait a minute."},
            headers={"Retry-After": str(_WINDOW_SECONDS)},
        )

    return await call_next(request)

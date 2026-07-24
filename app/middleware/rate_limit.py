"""
Rate limiting middleware.

Primary implementation uses Redis (sorted-set sliding window) so the limit
is enforced correctly across multiple worker processes / instances — the
previous in-process dict implementation allowed the effective limit to
multiply by the number of workers and reset on every deploy.

Falls back to a bounded in-process limiter if Redis is unavailable, so the
service still degrades to *some* protection rather than none.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

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
            # Bounded memory: drop the whole table rather than grow forever.
            # This briefly relaxes limits after eviction, which is an
            # acceptable trade-off for a fallback path.
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
    # Prefer an authenticated/application-supplied user id when present so
    # limits are per-user rather than per-NAT'd-IP; fall back to client host.
    user_id = request.headers.get("X-User-ID")
    if user_id:
        return f"user:{user_id.strip()[:128]}"
    client_host = request.client.host if request.client else "unknown"
    return f"ip:{client_host}"


def _redis_sliding_window_allowed(redis_client, key: str, limit: int) -> bool | None:
    """Returns True/False if Redis answered, or None if Redis is unavailable
    (caller should fall back to the local limiter in that case)."""
    try:
        now = time.time()
        cutoff = now - _WINDOW_SECONDS
        redis_key = f"ratelimit:{key}"

        pipe = redis_client.pipeline(transaction=True)
        pipe.zremrangebyscore(redis_key, 0, cutoff)
        pipe.zcard(redis_key)
        pipe.zadd(redis_key, {str(now): now})
        pipe.expire(redis_key, _WINDOW_SECONDS + 5)
        _, current_count, _, _ = pipe.execute()

        if current_count >= limit:
            # We already added the current attempt above; remove it since
            # this request is being rejected and shouldn't count against
            # the next window.
            redis_client.zrem(redis_key, str(now))
            return False
        return True
    except Exception as e:  # broad: any redis.RedisError subtype, connection issues
        logger.warning("Redis rate limiter unavailable (%s) — using local fallback", e)
        return None


async def rate_limit_middleware(request: Request, call_next):
    # Health and docs endpoints stay exempt so uptime monitors and API
    # exploration aren't rate-limited alongside real traffic.
    if request.url.path in {"/health", "/docs", "/openapi.json", "/redoc"}:
        return await call_next(request)

    client_key = _get_client_key(request)

    redis_client = None
    try:
        from app.services.memory_service import memory as _memory

        if _memory._is_redis_available():
            redis_client = _memory.redis
    except Exception:
        redis_client = None

    allowed: bool | None = None
    if redis_client is not None:
        allowed = _redis_sliding_window_allowed(redis_client, client_key, settings.RATE_LIMIT_RPM)

    if allowed is None:
        allowed = _local_limiter.is_allowed(client_key, settings.RATE_LIMIT_RPM)

    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please wait a minute."},
            headers={"Retry-After": str(_WINDOW_SECONDS)},
        )

    return await call_next(request)

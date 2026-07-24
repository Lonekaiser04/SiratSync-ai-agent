"""
Response cache with two backends:
  - RedisResponseCache: shared across all workers/instances (used whenever
    Redis is available — this is the correct choice for anything beyond a
    single-process deployment).
  - LocalResponseCache: thread-safe in-memory TTL cache, used as a fallback
    when Redis is unavailable (e.g. local dev without Redis configured).

The cache key is scoped per-user (previously the `user_id` parameter was
accepted but silently ignored, causing responses to leak across users for
any two users who happened to ask the same normalized question).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from datetime import datetime, timedelta
from typing import Optional

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_PERSONALIZATION_MARKERS = (
    "my ", " me ", " me?", " me.", "i'm", "i've", "i missed", "i prayed",
    " i ", "i'm ", "i am ",
)
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_message(message: str) -> str:
    normalized = message.lower().strip()
    normalized = normalized.replace("?", "").replace("please", "")
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    return normalized


def _is_personalized(message: str) -> bool:
    padded = f" {message.lower().strip()} "
    return any(marker in padded for marker in _PERSONALIZATION_MARKERS)


def _cache_key(message: str, user_id: str, scope: str = "chat") -> str:
    normalized = _normalize_message(message)
    digest = hashlib.sha256(f"{scope}:{user_id}:{normalized}".encode("utf-8")).hexdigest()
    return f"{settings.RESPONSE_CACHE_PREFIX}{scope}:{digest}"


class LocalResponseCache:
    """Thread-safe in-memory TTL cache, single-process only."""

    def __init__(self, max_entries: int = 2_000) -> None:
        self._cache: dict[str, tuple[str, datetime]] = {}
        self._lock = threading.Lock()
        self._max_entries = max_entries
        self.stats = {"hits": 0, "misses": 0}

    def get(self, message: str, user_id: str, scope: str = "chat") -> Optional[str]:
        key = _cache_key(message, user_id, scope)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self.stats["misses"] += 1
                return None
            response, expiry = entry
            if datetime.now() >= expiry:
                del self._cache[key]
                self.stats["misses"] += 1
                return None
            self.stats["hits"] += 1
            return response

    def set(
        self,
        message: str,
        user_id: str,
        response: str,
        ttl_minutes: int = 60,
        scope: str = "chat",
    ) -> None:
        if _is_personalized(message):
            return

        key = _cache_key(message, user_id, scope)
        expiry = datetime.now() + timedelta(minutes=ttl_minutes)

        with self._lock:
            self._cache[key] = (response, expiry)
            if len(self._cache) > self._max_entries:
                self._evict_expired_locked()
                # If still over budget, drop the oldest half to bound growth
                # even under a burst of unique never-expiring-soon keys.
                if len(self._cache) > self._max_entries:
                    overflow = len(self._cache) - self._max_entries
                    for k in list(self._cache.keys())[:overflow]:
                        del self._cache[k]

    def _evict_expired_locked(self) -> None:
        now = datetime.now()
        expired = [k for k, (_, exp) in self._cache.items() if now >= exp]
        for k in expired:
            del self._cache[k]

    def delete(self, message: str, user_id: str, scope: str = "chat") -> None:
        key = _cache_key(message, user_id, scope)
        with self._lock:
            self._cache.pop(key, None)


class RedisResponseCache:
    """Redis-backed cache, correct under multiple workers/instances."""

    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client
        self.stats = {"hits": 0, "misses": 0}
        # Local cache absorbs Redis outages without losing cache semantics
        # entirely; also serves as a cheap negative-lookup fallback.
        self._local_fallback = LocalResponseCache(max_entries=settings.LOCAL_CACHE_MAX_ENTRIES)

    def get(self, message: str, user_id: str, scope: str = "chat") -> Optional[str]:
        key = _cache_key(message, user_id, scope)
        try:
            value = self._redis.get(key)
            if value is not None:
                self.stats["hits"] += 1
                return value
            self.stats["misses"] += 1
            return None
        except redis.RedisError as e:
            logger.warning("Redis cache GET failed, falling back to local cache: %s", e)
            return self._local_fallback.get(message, user_id, scope)

    def set(
        self,
        message: str,
        user_id: str,
        response: str,
        ttl_minutes: int = 60,
        scope: str = "chat",
    ) -> None:
        if _is_personalized(message):
            return

        key = _cache_key(message, user_id, scope)
        try:
            self._redis.set(key, response, ex=timedelta(minutes=ttl_minutes))
        except redis.RedisError as e:
            logger.warning("Redis cache SET failed, falling back to local cache: %s", e)
            self._local_fallback.set(message, user_id, response, ttl_minutes, scope)

    def delete(self, message: str, user_id: str, scope: str = "chat") -> None:
        key = _cache_key(message, user_id, scope)
        try:
            self._redis.delete(key)
        except redis.RedisError as e:
            logger.warning("Redis cache DELETE failed: %s", e)


def _build_cache():
    """Reuse the memory service's Redis connection when available so we
    don't open a second connection pool just for caching."""
    try:
        from app.services.memory_service import memory as _memory

        if _memory.redis is not None and _memory._is_redis_available():
            logger.info("ResponseCache using shared Redis connection")
            return RedisResponseCache(_memory.redis)
    except Exception as e:  # pragma: no cover - defensive; fall back locally
        logger.warning("Could not attach response cache to Redis: %s", e)

    logger.info("ResponseCache using local in-memory store (single-process only)")
    return LocalResponseCache(max_entries=settings.LOCAL_CACHE_MAX_ENTRIES)


# Global cache instance — Redis-backed when possible, local otherwise.
cache = _build_cache()

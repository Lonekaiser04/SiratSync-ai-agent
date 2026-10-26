"""
Response cache with two backends:
  - RedisResponseCache: async Redis-backed cache shared across all instances.
  - LocalResponseCache: thread-safe in-memory TTL cache fallback.

Optimized to allow cross-user reuse of non-personalized queries and public
community post summaries, while safeguarding private/personalized conversations.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from datetime import datetime, timedelta
from typing import Optional

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
    if scope == "summarize":
        # Public post summaries can be reused across all users
        content_hash = hashlib.sha256(message.strip().encode("utf-8")).hexdigest()
        return f"{settings.SUMMARY_CACHE_PREFIX}{content_hash}"

    # Chat queries
    normalized = _normalize_message(message)
    # Non-personalized factual queries are shared cross-user
    digest = hashlib.sha256(f"chat:{normalized}".encode("utf-8")).hexdigest()
    return f"{settings.RESPONSE_CACHE_PREFIX}chat:{digest}"


class LocalResponseCache:
    """Thread-safe in-memory TTL cache, single-process fallback."""

    def __init__(self, max_entries: int = 2_000) -> None:
        self._cache: dict[str, tuple[str, datetime]] = {}
        self._lock = threading.Lock()
        self._max_entries = max_entries
        self.stats = {"hits": 0, "misses": 0}

    async def get(self, message: str, user_id: str = "default", scope: str = "chat") -> Optional[str]:
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

    async def set(
        self,
        message: str,
        user_id: str = "default",
        response: str = "",
        ttl_minutes: int = 60,
        scope: str = "chat",
    ) -> None:
        if scope == "chat" and _is_personalized(message):
            return

        key = _cache_key(message, user_id, scope)
        expiry = datetime.now() + timedelta(minutes=ttl_minutes)

        with self._lock:
            self._cache[key] = (response, expiry)
            if len(self._cache) > self._max_entries:
                self._evict_expired_locked()
                if len(self._cache) > self._max_entries:
                    overflow = len(self._cache) - self._max_entries
                    for k in list(self._cache.keys())[:overflow]:
                        del self._cache[k]

    def _evict_expired_locked(self) -> None:
        now = datetime.now()
        expired = [k for k, (_, exp) in self._cache.items() if now >= exp]
        for k in expired:
            del self._cache[k]

    async def delete(self, message: str, user_id: str = "default", scope: str = "chat") -> None:
        key = _cache_key(message, user_id, scope)
        with self._lock:
            self._cache.pop(key, None)

    async def clear(self) -> None:
        self.clear_sync()

    def clear_sync(self) -> None:
        with self._lock:
            self._cache.clear()


class RedisResponseCache:
    """Redis-backed async cache, shared across all instances."""

    def __init__(self) -> None:
        self.stats = {"hits": 0, "misses": 0}
        self._local_fallback = LocalResponseCache(max_entries=settings.LOCAL_CACHE_MAX_ENTRIES)

    def _get_redis(self):
        try:
            from app.services.memory_service import memory
            return memory.redis
        except Exception:
            return None

    async def get(self, message: str, user_id: str = "default", scope: str = "chat") -> Optional[str]:
        redis_client = self._get_redis()
        if redis_client is not None:
            key = _cache_key(message, user_id, scope)
            try:
                value = await redis_client.get(key)
                if value is not None:
                    self.stats["hits"] += 1
                    return value
                self.stats["misses"] += 1
                return None
            except Exception as e:
                logger.warning("Redis cache GET failed, falling back to local: %s", e)

        return await self._local_fallback.get(message, user_id, scope)

    async def set(
        self,
        message: str,
        user_id: str = "default",
        response: str = "",
        ttl_minutes: int = 60,
        scope: str = "chat",
    ) -> None:
        if scope == "chat" and _is_personalized(message):
            return

        redis_client = self._get_redis()
        if redis_client is not None:
            key = _cache_key(message, user_id, scope)
            try:
                await redis_client.set(key, response, ex=timedelta(minutes=ttl_minutes))
                return
            except Exception as e:
                logger.warning("Redis cache SET failed, falling back to local: %s", e)

        await self._local_fallback.set(message, user_id, response, ttl_minutes, scope)

    async def delete(self, message: str, user_id: str = "default", scope: str = "chat") -> None:
        redis_client = self._get_redis()
        if redis_client is not None:
            key = _cache_key(message, user_id, scope)
            try:
                await redis_client.delete(key)
                return
            except Exception as e:
                logger.warning("Redis cache DELETE failed: %s", e)

        await self._local_fallback.delete(message, user_id, scope)

    async def clear(self) -> None:
        redis_client = self._get_redis()
        if redis_client is not None:
            try:
                for prefix in (settings.RESPONSE_CACHE_PREFIX, settings.SUMMARY_CACHE_PREFIX):
                    keys = await redis_client.keys(f"{prefix}*")
                    if keys:
                        await redis_client.delete(*keys)
            except Exception as e:
                logger.warning("Redis cache clear failed: %s", e)
        self.clear_sync()

    def clear_sync(self) -> None:
        self._local_fallback.clear_sync()





# Global async cache instance
cache = RedisResponseCache()

"""
Redis-backed conversation memory and lightweight user profiling, with an
in-process fallback for local development / Redis outages.
Migrated to redis.asyncio to prevent blocking the asyncio event loop.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Any

from redis import asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_CHAT_TTL_SECONDS = 60 * 60 * 24 * 60      # 60 days
_STATS_TTL_SECONDS = 60 * 60 * 24 * 7      # 7 days
_ACTIVE_TTL_SECONDS = 60 * 60 * 24 * 60    # 60 days
_MAX_MESSAGES_STORED = 50
_REDIS_HEALTH_CACHE_SECONDS = 30

_POSITIVE_WORDS = frozenset(
    {"mashallah", "alhamdulillah", "achieved", "completed", "streak", "proud", "consistent"}
)
_STRUGGLE_WORDS = frozenset({"miss", "skip", "hard", "difficult", "struggle", "failed"})


class MemoryManager:
    """Thread-safe and async-safe memory manager using redis.asyncio."""

    def __init__(self) -> None:
        self.redis: aioredis.Redis | None = None
        self._pool: aioredis.ConnectionPool | None = None
        self.fallback_sessions: dict[str, list[dict]] = {}
        self.fallback_stats: dict[str, dict[str, int]] = {}
        self._fallback_lock = threading.Lock()
        self._last_health_check: datetime | None = None
        self._last_health_result: bool = False
        self._initialize_redis()

    # ── Connection setup ─────────────────────────────────────────────────
    def _initialize_redis(self) -> None:
        try:
            redis_url = os.environ.get("REDIS_URL")

            if redis_url:
                if settings.REDIS_SSL and redis_url.startswith("redis://"):
                    redis_url = redis_url.replace("redis://", "rediss://", 1)

                self._pool = aioredis.ConnectionPool.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
                    socket_connect_timeout=settings.REDIS_SOCKET_TIMEOUT,
                    max_connections=settings.REDIS_MAX_CONNECTIONS,
                    retry_on_timeout=True,
                    health_check_interval=30,
                )
                self.redis = aioredis.Redis(connection_pool=self._pool)
                logger.info("Configured async Redis pool via REDIS_URL")
            else:
                host = os.environ.get("UPSTASH_REDIS_HOST")
                password = os.environ.get("UPSTASH_REDIS_PASSWORD")
                port = int(os.environ.get("UPSTASH_REDIS_PORT", 6379))

                if host and password:
                    scheme = "rediss" if settings.REDIS_SSL or True else "redis"
                    self._pool = aioredis.ConnectionPool.from_url(
                        f"{scheme}://:{password}@{host}:{port}",
                        decode_responses=True,
                        socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
                        socket_connect_timeout=settings.REDIS_SOCKET_TIMEOUT,
                        max_connections=settings.REDIS_MAX_CONNECTIONS,
                        retry_on_timeout=True,
                        health_check_interval=30,
                    )
                    self.redis = aioredis.Redis(connection_pool=self._pool)
                    logger.info("Configured async Redis pool via env variables")
                else:
                    logger.info("No Redis credentials configured — using in-memory fallback")
                    self.redis = None
        except Exception as e:
            logger.warning("Error configuring async Redis pool: %s — using in-memory fallback", e)
            self.redis = None

    async def initialize(self) -> None:
        """Called at app startup to test connectivity asynchronously."""
        if self.redis is not None:
            try:
                await self.redis.ping()
                self._last_health_check = datetime.now()
                self._last_health_result = True
                logger.info("✅ Connected to async Redis successfully")
            except Exception as e:
                logger.warning("⚠️ Async Redis ping failed at startup: %s — using fallback", e)
                self._last_health_check = datetime.now()
                self._last_health_result = False

    async def close(self) -> None:
        """Gracefully close Redis connections on app shutdown."""
        if self.redis is not None:
            try:
                await self.redis.aclose()
                if self._pool is not None:
                    await self._pool.disconnect()
                logger.info("Closed async Redis connection pool")
            except Exception as e:
                logger.warning("Error closing async Redis connection: %s", e)

    async def is_redis_available(self) -> bool:
        """Cheap availability check, cached briefly to avoid a PING per call."""
        if self.redis is None:
            return False

        now = datetime.now()
        if (
            self._last_health_check is not None
            and (now - self._last_health_check).total_seconds() < _REDIS_HEALTH_CACHE_SECONDS
        ):
            return self._last_health_result

        try:
            await self.redis.ping()
            self._last_health_check = now
            self._last_health_result = True
            return True
        except Exception as e:
            if "event loop is closed" in str(e).lower():
                try:
                    self._initialize_redis()
                    if self.redis is not None:
                        await self.redis.ping()
                        self._last_health_check = now
                        self._last_health_result = True
                        return True
                except Exception:
                    pass
            logger.warning("Redis health check failed: %s", e)
            self._last_health_check = now
            self._last_health_result = False
            return False

    def _is_redis_available_sync(self) -> bool:
        """Non-blocking cached availability check for synchronous callers."""
        if self.redis is None:
            return False
        return self._last_health_result

    # ── Writes ───────────────────────────────────────────────────────────
    async def add_message(self, user_id: str, role: str, content: str) -> None:
        """Persist a chat message asynchronously and update lightweight engagement stats."""
        if not user_id or role not in {"user", "assistant"}:
            logger.warning("add_message called with invalid args: user_id=%r role=%r", user_id, role)
            return

        message_data = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }

        if await self.is_redis_available():
            try:
                chat_key = f"sirat:chat:{user_id}"
                active_key = f"sirat:active:{user_id}"
                stats_key = f"sirat:stats:{user_id}"

                async with self.redis.pipeline(transaction=False) as pipe:
                    pipe.rpush(chat_key, json.dumps(message_data))
                    pipe.ltrim(chat_key, -_MAX_MESSAGES_STORED, -1)
                    pipe.expire(chat_key, _CHAT_TTL_SECONDS)
                    pipe.set(active_key, datetime.now().isoformat())
                    pipe.expire(active_key, _ACTIVE_TTL_SECONDS)

                    if role == "user":
                        content_lower = content.lower()
                        pipe.hincrby(stats_key, "total_messages", 1)
                        if any(word in content_lower for word in _POSITIVE_WORDS):
                            pipe.hincrby(stats_key, "achievement_count", 1)
                        if any(word in content_lower for word in _STRUGGLE_WORDS):
                            pipe.hincrby(stats_key, "struggle_count", 1)
                        pipe.expire(stats_key, _STATS_TTL_SECONDS)

                    await pipe.execute()
                return
            except Exception as e:
                logger.warning("Redis pipeline error in add_message: %s — using fallback", e)

        self._fallback_add(user_id, message_data)

    def _fallback_add(self, user_id: str, message_data: dict) -> None:
        with self._fallback_lock:
            bucket = self.fallback_sessions.setdefault(user_id, [])
            bucket.append(message_data)
            if len(bucket) > _MAX_MESSAGES_STORED:
                self.fallback_sessions[user_id] = bucket[-_MAX_MESSAGES_STORED:]

    # ── Reads ────────────────────────────────────────────────────────────
    async def _get_recent_messages(self, user_id: str, count: int) -> list[dict]:
        if await self.is_redis_available():
            try:
                key = f"sirat:chat:{user_id}"
                raw_messages = await self.redis.lrange(key, -count, -1)
                messages = []
                for raw in raw_messages:
                    if not raw or not raw.strip():
                        continue
                    try:
                        messages.append(json.loads(raw))
                    except (json.JSONDecodeError, TypeError):
                        logger.warning("Skipping corrupt message entry for user %s", user_id)
                return messages
            except Exception as e:
                logger.warning("Redis error reading messages: %s — using fallback", e)

        with self._fallback_lock:
            return list(self.fallback_sessions.get(user_id, [])[-count:])

    async def get_recent_messages(self, user_id: str, count: int = 6) -> list[dict]:
        """Return the most recent messages as structured dicts: [{'role': ..., 'content': ...}, ...]."""
        return await self._get_recent_messages(user_id, count)

    async def get_context(self, user_id: str, max_messages: int = 8) -> str:
        messages = await self._get_recent_messages(user_id, max_messages)
        if not messages:
            return ""
        return "\n".join(
            f"{'User' if msg.get('role') == 'user' else 'Assistant'}: {msg.get('content', '')}"
            for msg in messages
        )

    async def get_last_question(self, user_id: str, exclude_current: str | None = None) -> str | None:
        messages = await self._get_recent_messages(user_id, 6)
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if exclude_current and content.strip().lower() == exclude_current.strip().lower():
                    continue
                return content
        return None

    async def get_last_bot_message(self, user_id: str) -> str | None:
        """Most recent assistant reply."""
        messages = await self._get_recent_messages(user_id, 6)
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                return msg.get("content")
        return None

    async def get_user_profile(self, user_id: str) -> dict[str, Any]:
        stats = {"total_messages": 0, "achievement_count": 0, "struggle_count": 0}

        if await self.is_redis_available():
            try:
                key = f"sirat:stats:{user_id}"
                async with self.redis.pipeline(transaction=False) as pipe:
                    pipe.hget(key, "total_messages")
                    pipe.hget(key, "achievement_count")
                    pipe.hget(key, "struggle_count")
                    results = await pipe.execute()

                if results[0] is not None:
                    stats["total_messages"] = int(results[0])
                if results[1] is not None:
                    stats["achievement_count"] = int(results[1])
                if results[2] is not None:
                    stats["struggle_count"] = int(results[2])
            except Exception as e:
                logger.warning("Failed to read user profile stats for %s: %s", user_id, e)

        consistency = "unknown"
        if stats["total_messages"] > 5:
            if stats["achievement_count"] > stats["struggle_count"] * 1.5:
                consistency = "high"
            elif stats["achievement_count"] > stats["struggle_count"] * 0.5:
                consistency = "medium"
            else:
                consistency = "struggling"

        return {
            "consistency": consistency,
            "topics": [],
            "message_count": stats["total_messages"],
            "suggested_advice": self._get_advice(consistency),
        }

    async def get_session_summary(self, user_id: str) -> dict[str, Any]:
        profile = await self.get_user_profile(user_id)
        has_messages = profile.get("message_count", 0) > 0
        is_redis = await self.is_redis_available()
        return {
            "active": has_messages,
            "message_count": profile.get("message_count", 0),
            "consistency": profile.get("consistency", "unknown"),
            "suggested_advice": profile.get("suggested_advice", ""),
            "using_redis": is_redis,
        }

    # ── Maintenance ──────────────────────────────────────────────────────
    async def cleanup_inactive_users(self, inactive_days: int = 60, batch_size: int = 500) -> int:
        """Delete Redis keys for users inactive beyond `inactive_days`."""
        if not await self.is_redis_available():
            return 0

        cleaned = 0
        try:
            async for key in self.redis.scan_iter("sirat:active:*", count=batch_size):
                user_id = key.split(":")[-1]
                if not await self.is_user_active(user_id, inactive_days):
                    try:
                        async with self.redis.pipeline(transaction=False) as pipe:
                            pipe.delete(f"sirat:chat:{user_id}")
                            pipe.delete(f"sirat:stats:{user_id}")
                            pipe.delete(key)
                            await pipe.execute()
                        cleaned += 1
                        logger.info("Cleaned up inactive user: %s", user_id)
                    except Exception as e:
                        logger.error("Failed to clean up user %s: %s", user_id, e)
        except Exception as e:
            logger.error("Cleanup scan failed: %s", e)

        return cleaned

    async def clear_session(self, user_id: str) -> dict[str, str]:
        if await self.is_redis_available():
            try:
                async with self.redis.pipeline(transaction=False) as pipe:
                    pipe.delete(f"sirat:chat:{user_id}")
                    pipe.delete(f"sirat:stats:{user_id}")
                    pipe.delete(f"sirat:active:{user_id}")
                    await pipe.execute()
                logger.info("Cleared Redis data for user: %s", user_id)
            except Exception as e:
                logger.error("Failed to clear Redis data for %s: %s", user_id, e)
                if "event loop is closed" in str(e).lower():
                    try:
                        self._initialize_redis()
                        if self.redis is not None:
                            await self.redis.delete(f"sirat:chat:{user_id}", f"sirat:stats:{user_id}", f"sirat:active:{user_id}")
                    except Exception:
                        pass

        with self._fallback_lock:
            self.fallback_sessions.pop(user_id, None)
            self.fallback_stats.pop(user_id, None)

        return {"status": "cleared", "user_id": user_id}

    async def get_last_active(self, user_id: str) -> datetime | None:
        if await self.is_redis_available():
            try:
                key = f"sirat:active:{user_id}"
                timestamp = await self.redis.get(key)
                if timestamp:
                    return datetime.fromisoformat(timestamp)
            except Exception as e:
                logger.warning("Failed to read last_active for %s: %s", user_id, e)
        return None

    async def is_user_active(self, user_id: str, days: int = 30) -> bool:
        last_active = await self.get_last_active(user_id)
        if last_active:
            return (datetime.now() - last_active).days < days
        return False

    def _get_advice(self, consistency: str) -> str:
        if consistency == "struggling":
            return "🤲 Start with just ONE prayer on time today. Allah loves small consistent deeds."
        if consistency == "high":
            return "🌟 MashaAllah! Consider adding morning adhkar to your routine."
        return "📌 Set a small daily goal in the Habit Tracker today."

    async def get_session_counts(self) -> dict[str, int]:
        """Lightweight session counts without scanning the entire keyspace."""
        if await self.is_redis_available():
            try:
                dbsize = await self.redis.dbsize()
                return {"redis_keys": dbsize, "fallback_sessions": len(self.fallback_sessions)}
            except Exception:
                pass
        return {"fallback_sessions": len(self.fallback_sessions)}

    @property
    def sessions(self) -> dict[str, int]:
        """Backward-compatible synchronous property for diagnostics."""
        return {"fallback_sessions": len(self.fallback_sessions)}


# Singleton instance used across the application.
memory = MemoryManager()

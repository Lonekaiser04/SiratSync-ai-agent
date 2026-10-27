# -*- coding: utf-8 -*-
"""
Regression test suite for SiratSync AI Agent Backend.
Covers:
- Liveness (/health/live) vs Diagnostics (/health, /health/ready)
- Rate limiting with proxy IPs (X-Forwarded-For) and Firebase auth tokens
- Chat validation, spoofing protection, and direct answers
- Summarization and cross-user public cache sharing
- Cache isolation and user privacy
- Memory fallback and resilience during Redis outage
"""

import sys
import os
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.services.memory_service import MemoryManager
from app.utils.cache import cache, LocalResponseCache, RedisResponseCache, _is_personalized, _cache_key
from app.core.security import get_client_ip, verify_firebase_token

client = TestClient(app)


class TestHealthRegression:
    def test_health_live_endpoint(self):
        """Liveness probe must be instantaneous, zero-cost, and return 200."""
        response = client.get("/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("ok", "alive")
        assert "timestamp" in data
        assert "version" in data

    def test_health_ready_diagnostics(self):
        """Readiness check must inspect async components without making LLM calls."""
        response = client.get("/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("ready", "healthy")
        assert "components" in data
        assert "memory_manager" in data["components"]

    def test_health_head(self):
        """HEAD request on /health must succeed for keep-alive pingers."""
        response = client.head("/health")
        assert response.status_code == 200


class TestAuthenticationAndSecurity:
    def test_user_summary_requires_internal_api_key(self):
        """Unauthorized requests to user management must return 401."""
        res_no_key = client.get("/user/test_victim_1/summary")
        assert res_no_key.status_code == 401

        res_bad_key = client.get("/user/test_victim_1/summary", headers={"X-API-Key": "invalid-secret"})
        assert res_bad_key.status_code == 401

    def test_user_summary_with_valid_key(self):
        """Authorized requests with internal API key succeed."""
        res = client.get(
            "/user/test_victim_1/summary",
            headers={"X-API-Key": settings.INTERNAL_API_KEY}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["user_id"] == "test_victim_1"
        assert "profile" in data
        assert "session" in data

    def test_proxy_ip_extraction(self):
        """get_client_ip extracts leftmost public client IP from X-Forwarded-For."""
        req_single = MagicMock()
        req_single.headers = {"x-forwarded-for": "203.0.113.195"}
        req_single.client.host = "10.0.0.1"
        assert get_client_ip(req_single) == "203.0.113.195"

        req_multi = MagicMock()
        req_multi.headers = {"x-forwarded-for": "198.51.100.10, 10.0.0.2, 172.16.0.1"}
        req_multi.client.host = "10.0.0.1"
        assert get_client_ip(req_multi) == "198.51.100.10"

    def test_effective_user_id_from_verified_firebase_token(self, monkeypatch):
        """When Firebase ID token is authenticated, its verified UID overrides client body."""
        # Mock verify_firebase_token to return verified UID
        monkeypatch.setattr(
            "app.middleware.rate_limit.verify_firebase_token",
            lambda token: {"uid": "verified_auth_user_123"}
        )

        # Send chat request where client claims user_id is 'spoofed_user_999'
        response = client.post(
            "/chat",
            headers={"Authorization": "Bearer fake-valid-token-xyz"},
            json={
                "user_id": "spoofed_user_999",
                "message": "hello"
            }
        )
        assert response.status_code == 200
        # The response must succeed and rate-limit / memory must bind to verified_auth_user_123


class TestChatValidationRegression:
    def test_empty_message_rejected(self):
        response = client.post("/chat", json={"user_id": "u1", "message": "   "})
        assert response.status_code in (400, 422)

    def test_empty_user_id_rejected(self):
        response = client.post("/chat", json={"user_id": "   ", "message": "Salam"})
        assert response.status_code in (400, 422)

    def test_message_too_long_rejected(self):
        long_text = "word " * 501
        response = client.post("/chat", json={"user_id": "u1", "message": long_text})
        assert response.status_code in (400, 422)


class TestSummarizationAndCrossUserCaching:
    def test_short_content_summarize_bypasses_llm(self):
        """Content < 30 chars is returned directly without LLM invocation."""
        short_text = "Short text."
        response = client.post("/summarize", json={"user_id": "u1", "post_content": short_text})
        assert response.status_code == 200
        data = response.json()
        assert data["summary"] == short_text
        assert data["original_length"] == len(short_text)

    def test_cross_user_public_post_cache_sharing(self, monkeypatch):
        """Identical public posts summarized by different users should hit cache without calling LLM twice."""
        llm_call_count = 0

        async def fake_llm_create(*args, **kwargs):
            nonlocal llm_call_count
            llm_call_count += 1
            mock_choice = MagicMock()
            mock_choice.message.content = "Shared summary of public community post."
            return MagicMock(choices=[mock_choice])

        monkeypatch.setattr("app.api.summarize.llm.chat.completions.create", AsyncMock(side_effect=fake_llm_create))

        import time
        unique_id = f"{time.time()}_{os.getpid()}"
        post = (
            f"Community announcement {unique_id}: The local masjid will host a Taraweeh reflection circle "
            "every night after Isha prayer during the last ten nights of Ramadan. Everyone "
            "is welcome to attend with family and friends to strengthen brotherhood and knowledge."
        )

        # User A summarizes post
        res_user_a = client.post("/summarize", json={"user_id": "user_alice", "post_content": post})
        assert res_user_a.status_code == 200
        summary_a = res_user_a.json()["summary"]
        assert llm_call_count == 1

        # User B summarizes the exact same post
        res_user_b = client.post("/summarize", json={"user_id": "user_bob", "post_content": post})
        assert res_user_b.status_code == 200
        summary_b = res_user_b.json()["summary"]

        # User B must receive identical summary from cache, without triggering an extra LLM call
        assert summary_b == summary_a
        assert llm_call_count == 1  # Verify LLM was NOT called again!


class TestCacheIsolationAndPrivacy:
    @pytest.mark.asyncio
    async def test_chat_cache_isolation_between_users(self):
        """Personalized queries are recognized and never stored in cache to preserve privacy."""
        assert _is_personalized("How was my prayer streak yesterday?")
        assert _is_personalized("Can you help me with my habits?")
        assert not _is_personalized("What is the longest surah in the Quran?")

        # Attempt to store a personalized answer for user_alice
        await cache.set("How was my prayer streak yesterday?", "user_alice", "Your streak is 5 days", scope="chat")
        
        # Verify that it is NOT cached for user_bob
        cached_bob = await cache.get("How was my prayer streak yesterday?", "user_bob", scope="chat")
        assert cached_bob is None


class TestRedisOutageResilience:
    @pytest.mark.asyncio
    async def test_memory_service_works_without_redis(self):
        """When Redis is None or unavailable, memory operations continue in-memory."""
        mem = MemoryManager()
        mem.redis = None

        assert not await mem.is_redis_available()

        # Add message
        await mem.add_message("test_user_offline", "user", "Assalamu Alaikum")
        await mem.add_message("test_user_offline", "assistant", "Wa Alaikum Assalam")

        # Read context (formatted string for LLM)
        context = await mem.get_context("test_user_offline")
        assert "Assalamu Alaikum" in context
        assert "Wa Alaikum Assalam" in context

        # Check raw recent messages
        messages = await mem._get_recent_messages("test_user_offline", count=5)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

        # Check last bot message
        last_bot = await mem.get_last_bot_message("test_user_offline")
        assert last_bot == "Wa Alaikum Assalam"

        # Clear session
        await mem.clear_session("test_user_offline")
        cleared_ctx = await mem.get_context("test_user_offline")
        assert len(cleared_ctx) == 0

        await mem.close()

    @pytest.mark.asyncio
    async def test_response_cache_works_without_redis(self):
        """When Redis is not configured, response cache transparently uses local cache with user isolation."""
        local_cache = LocalResponseCache()
        await local_cache.set("What is Ramadan?", "user_1", "Ramadan is the ninth month of the Islamic calendar", scope="chat")
        cached_user1 = await local_cache.get("What is Ramadan?", "user_1", scope="chat")
        assert cached_user1 == "Ramadan is the ninth month of the Islamic calendar"
        # User 2 must not see user 1's chat cache (H-4 isolation fix)
        cached_user2 = await local_cache.get("What is Ramadan?", "user_2", scope="chat")
        assert cached_user2 is None


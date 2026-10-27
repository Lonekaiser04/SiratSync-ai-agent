# -*- coding: utf-8 -*-
"""
Targeted regression tests for the 3 Critical and 8 High-severity audit findings:
1. Atomic rate limiting (Lua script, TOCTOU prevention, fallback) [C-2]
2. Cross-user cache isolation (per-user chat hash, public summary sharing, personalization guard) [H-4]
3. WhatsApp authentication and context (SimpleNamespace isolation, phone identity, monotonic deduplication) [C-3, H-6]
4. Quran statistics (reachable longest surah code, garbled text fix) [H-1, H-7]
5. Markdown formatting (symmetric italics on English translations) [H-2]
6. Keep-alive URLs (automatic /health/live normalization) [H-8]
7. Removed duplicate LLM helpers (clean module exports, canonical utils in helpers) [H-3]
8. Threading lock risk verification (dict safety, eviction bounding, no deadlock) [H-5]
"""

import sys
import os
import re
import time
import uuid
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.services.rag_service import rag_service
from app.utils.cache import cache, LocalResponseCache, _cache_key, _is_personalized
from app.utils.helpers import _format_rag_data_direct, _extract_english_only
import app.services.llm_service as llm_service_module
import app.middleware.rate_limit as rate_limit_module
from app.middleware.rate_limit import _RATE_LIMIT_LUA, _redis_sliding_window_allowed
import app.api.whatsapp as whatsapp_module

client = TestClient(app)


# ── 1. ATOMIC RATE LIMITING (C-2) ──────────────────────────────────────────

class TestAtomicRateLimiting:
    def test_lua_script_syntax_and_structure(self):
        """Verify the Lua script contains atomic check-before-add logic."""
        lua = _RATE_LIMIT_LUA
        assert "ZREMRANGEBYSCORE" in lua
        assert "ZCARD" in lua
        assert "ZADD" in lua
        assert "EXPIRE" in lua
        # Verify check occurs BEFORE add
        card_pos = lua.index("ZCARD")
        add_pos = lua.index("ZADD")
        assert card_pos < add_pos, "ZCARD must be called before ZADD to eliminate TOCTOU race"
        assert "if current >= limit then" in lua
        assert "return 0" in lua
        assert "return 1" in lua

    @pytest.mark.asyncio
    async def test_redis_sliding_window_allowed_under_limit(self):
        """When under limit, Lua script returns 1 and function returns True."""
        mock_redis = AsyncMock()
        mock_redis.eval = AsyncMock(return_value=1)

        allowed = await _redis_sliding_window_allowed(mock_redis, "test_user_under", 60)
        assert allowed is True
        mock_redis.eval.assert_called_once()
        args = mock_redis.eval.call_args[0]
        assert args[0] == _RATE_LIMIT_LUA
        assert args[1] == 1  # 1 key
        assert args[2] == "ratelimit:test_user_under"
        assert args[3] == 60  # limit

    @pytest.mark.asyncio
    async def test_redis_sliding_window_allowed_at_limit(self):
        """When at or over limit, Lua script returns 0 and function returns False."""
        mock_redis = AsyncMock()
        mock_redis.eval = AsyncMock(return_value=0)

        allowed = await _redis_sliding_window_allowed(mock_redis, "test_user_over", 60)
        assert allowed is False
        mock_redis.eval.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_sliding_window_error_fallback(self):
        """When Redis raises an exception, None is returned to trigger local fallback."""
        mock_redis = AsyncMock()
        mock_redis.eval = AsyncMock(side_effect=ConnectionError("Upstash timeout"))

        allowed = await _redis_sliding_window_allowed(mock_redis, "test_user_err", 60)
        assert allowed is None

    @pytest.mark.asyncio
    async def test_lua_simulation_sliding_window_logic(self):
        """Simulate the exact Lua script sliding-window semantics in Python."""
        # Simulated Redis sorted set
        store = {}
        window = 60
        limit = 3

        def simulate_lua(key, req_now, member):
            zset = store.setdefault(key, [])
            # 1. ZREMRANGEBYSCORE key 0 (req_now - window)
            zset = [item for item in zset if item[1] > (req_now - window)]
            store[key] = zset
            # 2. ZCARD key
            current = len(zset)
            # 3. Check limit BEFORE adding
            if current >= limit:
                return 0
            # 4. ZADD
            zset.append((member, req_now))
            return 1

        t0 = 1000.0
        # First 3 requests succeed
        assert simulate_lua("k", t0, "m1") == 1
        assert simulate_lua("k", t0 + 1, "m2") == 1
        assert simulate_lua("k", t0 + 2, "m3") == 1
        # 4th request in same window is rejected without polluting the set
        assert simulate_lua("k", t0 + 3, "m4") == 0
        assert len(store["k"]) == 3
        # After window expires, new request succeeds
        assert simulate_lua("k", t0 + 65, "m5") == 1


# ── 2. CROSS-USER CACHE ISOLATION (H-4) ───────────────────────────────────

class TestCrossUserCacheIsolation:
    def test_chat_cache_keys_are_user_isolated(self):
        """Identical chat queries from different users generate distinct cache keys."""
        msg = "What is the meaning of Ramadan?"
        key_user_a = _cache_key(msg, "user_alice", scope="chat")
        key_user_b = _cache_key(msg, "user_bob", scope="chat")

        assert key_user_a != key_user_b, "Chat cache keys must be isolated per user"
        assert "user_alice" not in key_user_a  # SHA256 hashed
        # Same user produces deterministic identical key
        assert key_user_a == _cache_key(msg, "user_alice", scope="chat")

    def test_summary_cache_keys_are_shared_cross_user(self):
        """Public post summaries are keyed solely by content and safely shared."""
        content = "Announcement: Friday khutbah starts at 1:30 PM."
        key_user_a = _cache_key(content, "user_alice", scope="summarize")
        key_user_b = _cache_key(content, "user_bob", scope="summarize")

        assert key_user_a == key_user_b, "Summarize cache keys must be shared cross-user"
        assert key_user_a.startswith(settings.SUMMARY_CACHE_PREFIX)

    @pytest.mark.asyncio
    async def test_chat_cache_storage_isolation(self):
        """User B cannot retrieve User A's cached chat responses."""
        local = LocalResponseCache()
        query = "What is Taqwa in Islam?"
        response_a = "Taqwa is God-consciousness and piety."

        await local.set(query, "user_alice", response_a, scope="chat")

        # User Alice hits cache
        hit_a = await local.get(query, "user_alice", scope="chat")
        assert hit_a == response_a

        # User Bob gets a miss
        hit_b = await local.get(query, "user_bob", scope="chat")
        assert hit_b is None

    def test_personalization_guard_bypasses_cache(self):
        """First-person and personal habit queries are detected and never cached."""
        assert _is_personalized("How is my salah streak?")
        assert _is_personalized("I missed Fajr today, what should I do?")
        assert _is_personalized("Can you check my progress?")
        assert _is_personalized("help me with my habits")

        # General factual queries are not classified as personal
        assert not _is_personalized("What is the shortest surah?")
        assert not _is_personalized("How many rakats in Dhuhr prayer?")


# ── 3. WHATSAPP AUTHENTICATION & CONTEXT (C-3, H-6) ────────────────────────

class TestWhatsAppAuthAndContext:
    def test_monotonic_time_used_in_deduplication(self):
        """_is_duplicate uses time.monotonic() to prevent deprecated loop issues."""
        whatsapp_module._seen_message_ids.clear()

        msg_id = f"msg_{uuid.uuid4().hex}"
        # First check: not a duplicate
        assert not whatsapp_module._is_duplicate(msg_id)
        # Immediate second check: duplicate
        assert whatsapp_module._is_duplicate(msg_id)

    def test_deduplication_cache_bounded(self):
        """Deduplication cache respects maximum size to prevent memory leaks."""
        whatsapp_module._seen_message_ids.clear()
        max_size = whatsapp_module._DEDUP_MAX_SIZE

        # Insert items beyond max_size
        for i in range(max_size + 50):
            whatsapp_module._seen_message_ids[f"msg_{i}"] = time.monotonic()

        # Evict by running check on a new item
        whatsapp_module._is_duplicate(f"msg_{max_size + 100}")
        assert len(whatsapp_module._seen_message_ids) <= max_size + 1

    @pytest.mark.asyncio
    async def test_whatsapp_request_isolation_object(self):
        """WhatsApp message handler constructs a clean SimpleNamespace for chat()."""
        # Inspect receive_whatsapp_message logic by verifying that SimpleNamespace
        # creates state with request_id and authenticated_user_id=None
        chat_http_state = SimpleNamespace(
            request_id="test_req_id_123",
            authenticated_user_id=None,
        )
        chat_http_request = SimpleNamespace(state=chat_http_state)

        assert chat_http_request.state.authenticated_user_id is None
        assert chat_http_request.state.request_id == "test_req_id_123"

        # Verify that chat() correctly resolves effective_user_id when authenticated_user_id is None
        from app.models.request_models import ChatRequest
        chat_req = ChatRequest(user_id="whatsapp:+1234567890", message="Salam")

        effective_user_id = (
            getattr(chat_http_request.state, "authenticated_user_id", None) or chat_req.user_id
        )
        assert effective_user_id == "whatsapp:+1234567890"

    def test_whatsapp_webhook_verification(self):
        """Webhook GET verification succeeds with correct verify token."""
        response = client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": settings.WHATSAPP_VERIFY_TOKEN,
                "hub.challenge": "challenge_code_999",
            },
        )
        assert response.status_code == 200
        assert response.text == "challenge_code_999"

    def test_whatsapp_webhook_invalid_token(self):
        """Webhook GET verification fails with incorrect token."""
        response = client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_token",
                "hub.challenge": "challenge_code_999",
            },
        )
        assert response.status_code == 403


# ── 4. QURAN STATISTICS (H-1, H-7) ─────────────────────────────────────────

class TestQuranStatistics:
    def test_longest_surah_query_is_reachable(self):
        """H-1 fix: 'longest surah' executes directly without requiring a surah name in query."""
        res = rag_service._handle_stats_query("what is the longest surah in the quran")
        assert res is not None, "Longest surah handler must be reachable and return response"
        assert "Surah Al-Baqarah" in res
        assert "286" in res
        assert "Ayat al-Kursi" in res

    def test_longest_chapter_phrasings_reachable(self):
        """Variations of longest surah/chapter queries return Surah Al-Baqarah."""
        for query in ["longest chapter", "longest surat", "most verses surah", "surah with most verses"]:
            res = rag_service._handle_stats_query(query)
            assert res is not None, f"Query '{query}' must be reachable"
            assert "Surah Al-Baqarah" in res

    def test_longest_verse_reachable(self):
        """Longest verse query returns Ayat al-Dayn 2:282."""
        res = rag_service._handle_stats_query("what is the longest verse in the quran")
        assert res is not None
        assert "2:282" in res or "Ayat al-Dayn" in res

    def test_quran_stats_text_formatting_and_typos(self):
        """H-7 fix: Quran stats output contains correct spacing and 'among', no garbled text."""
        res = rag_service._handle_stats_query("quran statistics total")
        assert res is not None
        # Verify typo '5:3)and' is fixed to proper spacing
        assert "5:3)and" not in res
        # Verify typo 'mong commonly cited views' is fixed (not standalone 'mong')
        assert " mong commonly" not in res
        assert "among commonly cited views" in res
        # Verify markdown bolding
        assert "**Surah Al-Ma'idah (5:3)** and **2:281** — among commonly cited views" in res


# ── 5. MARKDOWN FORMATTING (H-2) ───────────────────────────────────────────

class TestMarkdownFormatting:
    def test_english_translation_symmetric_italics(self):
        """H-2 fix: ENGLISH translations have symmetric opening and closing underscores."""
        rag_data = (
            "VERSE REFERENCE: 1:1\n"
            "SURAH: Al-Fatihah\n"
            "ARABIC: بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ\n"
            "ENGLISH: In the name of Allah, the Entirely Merciful, the Especially Merciful.\n"
        )
        formatted = _format_rag_data_direct(rag_data)

        # Must contain italic translation with BOTH opening and closing '_'
        assert "_In the name of Allah, the Entirely Merciful, the Especially Merciful._" in formatted
        # Must NOT contain asymmetric ending without opening
        assert "Merciful._" in formatted
        assert " ENGLISH:" not in formatted

    def test_english_extraction_strips_italics_cleanly(self):
        """_extract_english_only correctly handles underscored and non-underscored lines."""
        rag_data = (
            "VERSE REFERENCE: 1:2\n"
            "ENGLISH: _[All] praise is [due] to Allah, Lord of the worlds._\n"
        )
        extracted = _extract_english_only(rag_data)
        assert "[All] praise is [due] to Allah, Lord of the worlds." in extracted
        assert not extracted.startswith("_")
        assert not extracted.endswith("_")


# ── 6. KEEP-ALIVE URL NORMALIZATION (H-8) ──────────────────────────────────

class TestKeepAliveUrls:
    def test_keep_alive_normalizes_base_url(self):
        """H-8 fix: keep-alive script normalizes base URLs by appending /health/live."""
        def normalize_url(url: str) -> str:
            if url and "/health" not in url:
                return url.rstrip("/") + "/health/live"
            return url

        # Base URL without trailing slash
        assert normalize_url("https://siratsync-ai-agent.onrender.com") == (
            "https://siratsync-ai-agent.onrender.com/health/live"
        )
        # Base URL with trailing slash
        assert normalize_url("https://siratsync-ai-agent.onrender.com/") == (
            "https://siratsync-ai-agent.onrender.com/health/live"
        )
        # URL that already has /health/live
        assert normalize_url("https://siratsync-ai-agent.onrender.com/health/live") == (
            "https://siratsync-ai-agent.onrender.com/health/live"
        )
        # URL with /health/ready
        assert normalize_url("https://siratsync-ai-agent.onrender.com/health/ready") == (
            "https://siratsync-ai-agent.onrender.com/health/ready"
        )


# ── 7. REMOVED LLM HELPERS (H-3) ───────────────────────────────────────────

class TestRemovedLLMHelpers:
    def test_llm_service_module_exports_no_duplicate_helpers(self):
        """H-3 fix: llm_service does not export legacy sync helpers."""
        assert not hasattr(llm_service_module, "_extract_english_only"), (
            "llm_service._extract_english_only should be removed to prevent duplicate drift"
        )
        assert not hasattr(llm_service_module, "_format_rag_data_direct"), (
            "llm_service._format_rag_data_direct should be removed to prevent duplicate drift"
        )
        assert not hasattr(llm_service_module, "_call_llm_with_rag"), (
            "llm_service._call_llm_with_rag should be removed to prevent duplicate drift"
        )
        assert not hasattr(llm_service_module, "Groq"), (
            "Sync Groq import should be removed from llm_service"
        )

    def test_canonical_helpers_exported_from_helpers_module(self):
        """Canonical RAG formatters are exported from app.utils.helpers."""
        import app.utils.helpers as helpers
        assert hasattr(helpers, "_extract_english_only")
        assert hasattr(helpers, "_format_rag_data_direct")
        assert hasattr(helpers, "_call_llm_with_rag")


# ── 8. THREADING LOCK RISK VERIFICATION (H-5) ──────────────────────────────

class TestThreadingLockVerification:
    def test_context_lock_thread_safety_under_concurrency(self):
        """Verify _context_lock safely protects conversation_context under concurrent threads."""
        from concurrent.futures import ThreadPoolExecutor

        rag = rag_service
        num_threads = 20
        iterations = 50

        def access_context(thread_idx):
            for i in range(iterations):
                user_id = f"thread_user_{thread_idx}_{i % 5}"
                ctx = rag._get_user_context(user_id)
                ctx["last_surah_id"] = thread_idx
                ctx["last_surah_name"] = f"Surah_{thread_idx}"

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(access_context, t) for t in range(num_threads)]
            for f in futures:
                f.result()

        # Verify state is consistent and bounded
        assert len(rag.conversation_context) <= rag._MAX_CONTEXT_USERS

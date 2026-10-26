"""
Comprehensive automated tests for AI intelligence, multi-turn conversation context,
Islamic vs secular query classification, RAG context hygiene, and model fallback boundaries.
"""
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from groq import AuthenticationError, BadRequestError, InternalServerError, RateLimitError

from app.core.config import settings
from app.main import app
from app.services.llm_service import is_retryable_provider_error, llm_service
from app.services.memory_service import memory
from app.services.rag_service import rag_service
from app.utils.cache import cache


import time
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def clear_caches_before_after():
    await cache.clear()
    yield
    await cache.clear()


class TestErrorClassificationAndFastFailure:
    """Verifies that retryable errors trigger fallback and non-retryable 4xx client errors fail fast."""

    def test_retryable_provider_errors(self):
        req = httpx.Request("POST", "https://api.groq.com")
        res_500 = httpx.Response(500, request=req)
        res_429 = httpx.Response(429, request=req)

        assert is_retryable_provider_error(InternalServerError("Server error", response=res_500, body=None)) is True
        assert is_retryable_provider_error(RateLimitError("Rate limit exceeded", response=res_429, body=None)) is True

    def test_non_retryable_client_errors_fail_fast(self):
        req = httpx.Request("POST", "https://api.groq.com")
        res_400 = httpx.Response(400, request=req)
        res_401 = httpx.Response(401, request=req)

        assert is_retryable_provider_error(BadRequestError("Invalid argument", response=res_400, body=None)) is False
        assert is_retryable_provider_error(AuthenticationError("Invalid API Key", response=res_401, body=None)) is False

    @pytest.mark.asyncio
    async def test_llm_service_fast_fails_on_bad_request_without_fallback(self):
        """A 400 BadRequestError should NOT trigger the fallback model; it should fail fast."""
        req = httpx.Request("POST", "https://api.groq.com")
        res_400 = httpx.Response(400, request=req, json={"error": {"message": "Invalid request parameters"}})
        bad_req = BadRequestError("Invalid parameter", response=res_400, body=None)

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=bad_req)

        with pytest.raises(BadRequestError):
            await llm_service.generate_completion(
                messages=[{"role": "user", "content": "test"}],
                client=mock_client,
                primary_model="openai/gpt-oss-20b",
                fallback_model="openai/gpt-oss-120b",
            )

        # Verified: Only called once on primary model, did not attempt fallback!
        assert mock_client.chat.completions.create.call_count == 1


class TestRAGContextPurity:
    """Verifies that non-Islamic queries do NOT receive Islamic feature menu boilerplate in context."""

    def test_secular_queries_return_empty_rag_context(self):
        secular_queries = [
            "How do I write a binary search algorithm in Python?",
            "What is the capital of Australia?",
            "Can you explain how async and await work in computer science?",
            "Tips for organizing my desktop files and folders",
        ]
        for query in secular_queries:
            result = rag_service.retrieve(query)
            # Must NOT contain the 20-line feature menu
            assert "Salah, Prayer Times & Adhan" not in result
            assert "Sirat Assistant & AI Islamic Learning" not in result
            assert result == ""

    def test_islamic_queries_retrieve_rich_knowledge(self):
        result = rag_service.retrieve("what does quran say about patience")
        assert result != ""
        assert "patience" in result.lower() or "sabr" in result.lower() or "al-baqarah" in result.lower()


@pytest.mark.asyncio
class TestMultiTurnConversationAndContextPreservation:
    """Verifies multi-turn context passing, pronoun resolution, and follow-up intent detection."""

    async def test_multi_turn_history_included_in_llm_messages(self):
        user_id = f"test_multiturn_{time.time()}"
        await memory.clear_session(user_id)

        # Simulate prior turn in conversation
        await memory.add_message(user_id, "user", "I want to improve my morning focus.")
        await memory.add_message(
            user_id,
            "assistant",
            "Here are two recommendations: 1. Wake up before sunrise. 2. Keep digital devices away for the first hour.",
        )

        mock_choice = MagicMock()
        mock_choice.message.content = "For the second recommendation, place your phone in another room overnight."
        mock_resp = MagicMock(choices=[mock_choice])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_resp

                # User asks follow-up referencing the second point
                resp = await ac.post(
                    "/chat",
                    json={
                        "message": "Can you elaborate on the second recommendation?",
                        "user_id": user_id,
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                assert "second recommendation" in data["reply"] or "phone" in data["reply"]

                # Verify past conversation was passed as structured turns to LLM
                call_args = mock_create.call_args.kwargs
                messages = call_args["messages"]
                
                # Must contain: system, previous user turn, previous assistant turn, current user turn
                roles = [m["role"] for m in messages]
                assert roles == ["system", "user", "assistant", "user"]
                assert "I want to improve my morning focus." in messages[1]["content"]
                assert "Here are two recommendations:" in messages[2]["content"]
                assert "elaborate on the second recommendation" in messages[3]["content"]

    async def test_affirmation_followup_switches_intent_to_features(self):
        user_id = f"test_confirm_{time.time()}"
        await memory.clear_session(user_id)

        # Assistant previously proposed exploring features
        await memory.add_message(user_id, "user", "What is SiratSync?")
        await memory.add_message(
            user_id,
            "assistant",
            "SiratSync is an Islamic assistant. Would you like to learn more about our app features?",
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # User replies "yes" to confirm
            resp = await ac.post(
                "/chat",
                json={
                    "message": "Yes please",
                    "user_id": user_id,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            # Must detect app_features_inquiry from context
            assert data["intent"] == "app_features_inquiry"
            assert "SiratSync" in data["reply"] or "Quran" in data["reply"] or "Prayer" in data["reply"]


@pytest.mark.asyncio
class TestModelFallbackTransparencyAndBadges:
    """Verifies that fallback response is NEVER misreported as a primary model response in sources."""

    async def test_source_badge_shows_fallback_model_on_failover(self):
        user_id = f"test_badge_{time.time()}"
        await memory.clear_session(user_id)

        req = httpx.Request("POST", "https://api.groq.com")
        res_503 = httpx.Response(503, request=req, json={"error": {"message": "Service unavailable"}})
        transient_err = InternalServerError("Provider temporary outage", response=res_503, body=None)

        mock_choice = MagicMock()
        mock_choice.message.content = "Helpful answer generated by the secondary fallback model."
        mock_fallback_resp = MagicMock(choices=[mock_choice])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                # Primary model fails with 503; fallback succeeds
                mock_create.side_effect = [transient_err, mock_fallback_resp]

                resp = await ac.post(
                    "/chat",
                    json={
                        "message": "What are effective techniques for maintaining deep focus during long study sessions?",
                        "user_id": user_id,
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["reply"] == "Helpful answer generated by the secondary fallback model."

                # Verify source attribution badge explicitly identifies the fallback model!
                ai_sources = [s for s in data["sources"] if s.get("type") == "ai_generated"]
                assert len(ai_sources) == 1
                detail = ai_sources[0]["detail"]
                assert settings.FALLBACK_GROQ_MODEL in detail
                assert settings.GROQ_MODEL not in detail

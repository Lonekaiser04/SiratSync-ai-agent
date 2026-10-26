"""
Tests for Groq model resolution, NotFoundError (404) automatic fallback,
provider failure handling, correct logging, and direct Quran/RAG response preservation.
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
import httpx
from groq import GroqError, NotFoundError

from app.core.config import settings
from app.main import app
from app.utils.cache import cache


@pytest_asyncio.fixture(autouse=True)
async def clear_cache_before_and_after():
    await cache.clear()
    yield
    await cache.clear()



@pytest.mark.asyncio
class TestGroqModelResolutionAndFallback:
    """Tests covering successful LLM generation and 404 NotFoundError model fallback."""

    async def test_successful_llm_generation_with_configured_model(self):
        """Test standard successful generation logs success and attaches correct source attribution."""
        mock_choice = MagicMock()
        mock_choice.message.content = "Building positive habits requires gradual consistency and regular self-reflection."
        mock_response = MagicMock(choices=[mock_choice])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create, \
                 patch("app.api.chat.logger") as mock_logger:
                mock_create.return_value = mock_response

                resp = await ac.post(
                    "/chat",
                    json={
                        "message": "What are effective strategies for maintaining focus during difficult tasks?",
                        "user_id": "test_user_success",
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                assert "Building positive habits" in data["reply"]
                
                # Verify AI source was attached with the active model
                ai_sources = [s for s in data["sources"] if s.get("type") == "ai_generated"]
                assert len(ai_sources) == 1
                assert settings.GROQ_MODEL in ai_sources[0]["detail"]

                # Verify success was logged with model name
                info_logs = [call[0][0] for call in mock_logger.info.call_args_list if call[0]]
                assert any("LLM reply generated successfully" in msg for msg in info_logs)

                # Verify response was cached
                cached = await cache.get("What are effective strategies for maintaining focus during difficult tasks?", "test_user_success")
                assert cached is not None

    async def test_model_not_found_404_recovers_via_fallback_model(self):
        """
        When the configured model raises a 404 NotFoundError (model_not_found),
        the endpoint should catch it, log a warning, retry with FALLBACK_GROQ_MODEL,
        and succeed.
        """
        req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        res = httpx.Response(404, request=req, json={"error": {"code": "model_not_found", "message": "Model not found"}})
        nfe = NotFoundError("The model 'llama-3.3-70b-versatile' does not exist or you do not have access to it.", response=res, body=None)

        mock_choice = MagicMock()
        mock_choice.message.content = "Response from the resilient fallback model."
        mock_fallback_response = MagicMock(choices=[mock_choice])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create, \
                 patch("app.api.chat.logger") as mock_logger, \
                 patch.object(settings, "GROQ_MODEL", "unavailable-invalid-model"):

                # First call raises NotFoundError; second call (with fallback) succeeds
                mock_create.side_effect = [nfe, mock_fallback_response]

                resp = await ac.post(
                    "/chat",
                    json={
                        "message": "Give me some guidance on structuring my morning routine.",
                        "user_id": "test_user_fallback",
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["reply"] == "Response from the resilient fallback model."

                # Verify fallback model was called
                assert mock_create.call_count == 2
                assert mock_create.call_args_list[0].kwargs["model"] == "unavailable-invalid-model"
                assert mock_create.call_args_list[1].kwargs["model"] == settings.FALLBACK_GROQ_MODEL

                # Verify source shows the fallback model
                ai_sources = [s for s in data["sources"] if s.get("type") == "ai_generated"]
                assert len(ai_sources) == 1
                assert settings.FALLBACK_GROQ_MODEL in ai_sources[0]["detail"]

                # Verify warning was logged about the 404 fallback
                warning_logs = [call[0][0] for call in mock_logger.warning.call_args_list if call[0]]
                assert any("Configured Groq model" in msg and "Falling back" in msg for msg in warning_logs)


@pytest.mark.asyncio
class TestProviderFailureAndMisleadingLogs:
    """Tests ensuring provider failures return user-friendly apologies, avoid misleading logs, and do not cache errors."""

    async def test_provider_groq_error_returns_fallback_and_logs_warning_not_success(self):
        """
        When Groq API raises GroqError:
        - Must log error and fallback warning
        - Must NOT log 'LLM reply generated successfully'
        - Must NOT cache the fallback reply
        - Must NOT claim ai_generated source
        """
        req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        res = httpx.Response(500, request=req)
        provider_error = GroqError("Internal server error from Groq upstream")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create, \
                 patch("app.api.chat.logger") as mock_logger:

                mock_create.side_effect = provider_error

                resp = await ac.post(
                    "/chat",
                    json={
                        "message": "How do I overcome procrastination when working on difficult tasks?",
                        "user_id": "test_user_failure",
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                assert "having trouble reaching my knowledge service" in data["reply"]

                # Check logged messages
                for call in mock_logger.info.call_args_list:
                    msg = call[0][0] if call[0] else ""
                    assert "LLM reply generated successfully" not in msg

                # Check fallback warning was logged
                warning_messages = [call[0][0] for call in mock_logger.warning.call_args_list]
                assert any("Fallback response returned" in msg for msg in warning_messages)

                # Check sources do NOT attribute fallback apology to ai_generated
                ai_sources = [s for s in data["sources"] if s.get("type") == "ai_generated"]
                assert len(ai_sources) == 0

                # Check response was NOT cached
                cached = await cache.get("How do I overcome procrastination when working on difficult tasks?", "test_user_failure")
                assert cached is None

    async def test_empty_llm_response_handled_as_fallback(self):
        """When LLM returns empty whitespace, handle as fallback without caching."""
        mock_choice = MagicMock()
        mock_choice.message.content = "   "
        mock_response = MagicMock(choices=[mock_choice])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create, \
                 patch("app.api.chat.logger") as mock_logger:

                mock_create.return_value = mock_response

                resp = await ac.post(
                    "/chat",
                    json={
                        "message": "Give me general advice on organizing my schedule.",
                        "user_id": "test_user_empty",
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                assert "wasn't able to form a complete answer" in data["reply"]

                # Check fallback warning logged
                warning_messages = [call[0][0] for call in mock_logger.warning.call_args_list]
                assert any("LLM returned empty content" in msg for msg in warning_messages)
                assert any("Fallback response returned" in msg for msg in warning_messages)

                # Not cached
                cached = await cache.get("Give me general advice on organizing my schedule.", "test_user_empty")
                assert cached is None


@pytest.mark.asyncio
class TestDirectQuranAndRAGPreservation:
    """Tests verifying direct Quran verses, RAG queries, and app features bypass LLM completely."""

    async def test_direct_verse_reference_query_bypasses_llm(self):
        """Querying '2:255' (Ayat al-Kursi) must return direct Quran data without touching Groq."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                resp = await ac.post(
                    "/chat",
                    json={
                        "message": "2:255",
                        "user_id": "test_user_verse",
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                # Ayatul Kursi reference and translation
                assert "Al-Baqarah" in data["reply"] and "2:255" in data["reply"]
                assert ("Allah" in data["reply"] or "اللَّهُ" in data["reply"] or "ٱللَّهُ" in data["reply"])
                # LLM was never called!
                mock_create.assert_not_called()

                # Sources reflect sacred Quran translation
                quran_sources = [s for s in data["sources"] if s.get("type") == "quran"]
                assert len(quran_sources) >= 1

    async def test_direct_features_query_bypasses_llm(self):
        """Querying 'features' must return instant knowledge base response without LLM call."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.chat.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                resp = await ac.post(
                    "/chat",
                    json={
                        "message": "What are the features of SiratSync?",
                        "user_id": "test_user_feat",
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                assert "SiratSync Features:" in data["reply"]
                mock_create.assert_not_called()
                kb_sources = [s for s in data["sources"] if s.get("type") == "knowledge_base"]
                assert len(kb_sources) == 1

    async def test_quran_topic_rag_fallback_on_llm_failure(self):
        """When an Islamic topic query is processed with RAG, but LLM fails, direct RAG data is preserved."""
        from app.utils.helpers import _call_llm_with_rag

        sample_rag_data = "SURAH: Al-Baqarah\nVERSE REFERENCE: 2:153\nENGLISH: O you who have believed, seek help through patience and prayer."
        
        with patch("app.utils.helpers._rag_llm_client.chat.completions.create", new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = GroqError("Service timeout")
            
            result = await _call_llm_with_rag(
                user_query="Tell me about patience in the Quran",
                rag_data=sample_rag_data,
                user_profile={},
            )
            # Must preserve the Quranic text from the RAG data directly!
            assert "seek help through patience and prayer" in result or "Al-Baqarah" in result


@pytest.mark.asyncio
class TestSummarizeAndHealthFallback:
    """Tests covering summarize endpoint and health endpoint model fallback."""

    async def test_summarize_recovers_via_fallback_model(self):
        """Summarize endpoint falls back to FALLBACK_GROQ_MODEL when 404 occurs."""
        req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        res = httpx.Response(404, request=req, json={"error": {"code": "model_not_found"}})
        nfe = NotFoundError("Model not found", response=res, body=None)

        mock_choice = MagicMock()
        mock_choice.message.content = "Succinct post summary from fallback model."
        mock_fallback_response = MagicMock(choices=[mock_choice])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.summarize.llm.chat.completions.create", new_callable=AsyncMock) as mock_create, \
                 patch.object(settings, "GROQ_MODEL", "unavailable-invalid-model"):

                mock_create.side_effect = [nfe, mock_fallback_response]

                resp = await ac.post(
                    "/summarize",
                    json={
                        "post_content": "Unique community post for fallback test: Today our local study circle reflected deeply on humility, good character, and mutual support across the neighborhood.",
                        "user_id": "test_user_sum",
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["summary"] == "Succinct post summary from fallback model."
                assert mock_create.call_count == 2
                assert mock_create.call_args_list[1].kwargs["model"] == settings.FALLBACK_GROQ_MODEL

    async def test_health_endpoint_reports_model_and_fallback(self):
        """Health diagnostics accurately expose configured model and fallback model."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] in ("healthy", "degraded")
            assert "model" in data["components"]
            assert "fallback_model" in data["components"]
            assert data["components"]["fallback_model"] == settings.FALLBACK_GROQ_MODEL

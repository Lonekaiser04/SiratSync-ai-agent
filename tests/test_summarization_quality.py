"""
Comprehensive automated tests for Post-Summarization pipeline quality,
preprocessing, adaptive token limits, multilingual handling, and edge cases.
"""
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from groq import InternalServerError, RateLimitError

from app.api.summarize import (
    clean_summary_output,
    preprocess_post_content,
    _get_adaptive_max_tokens,
)
from app.core.config import settings
from app.main import app
from app.utils.cache import cache


import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def clear_caches_before_after():
    await cache.clear()
    yield
    await cache.clear()


class TestSummarizationPreprocessing:
    """Tests covering input sanitization, noise removal, and trivial edge cases."""

    def test_strip_zero_width_characters(self):
        raw = "Bismillah\u200b\u200c\u200d\ufeff\u00ad this is a blessed community post."
        cleaned, is_trivial = preprocess_post_content(raw)
        assert "\u200b" not in cleaned
        assert "\u200c" not in cleaned
        assert "\ufeff" not in cleaned
        assert cleaned == "Bismillah this is a blessed community post."
        assert not is_trivial

    def test_collapse_repeated_punctuation(self):
        raw = "Important announcement for all community members!!!!!!!! Please arrive on time?????"
        cleaned, is_trivial = preprocess_post_content(raw)
        assert "!!!!!!!!" not in cleaned
        assert "!!!!!" not in cleaned
        assert "!!" in cleaned
        assert "??" in cleaned

    def test_normalize_excessive_whitespace_and_newlines(self):
        raw = "First line of reminder.\n\n\n\n\nSecond line with   lots   of   spaces."
        cleaned, is_trivial = preprocess_post_content(raw)
        assert "\n\n\n" not in cleaned
        assert "\n\n" in cleaned
        assert "   " not in cleaned
        assert "lots of spaces" in cleaned

    def test_empty_or_whitespace_input_is_trivial(self):
        assert preprocess_post_content("")[1] is True
        assert preprocess_post_content("   \n\t  ")[1] is True
        assert preprocess_post_content(None)[1] is True

    def test_symbol_only_input_is_trivial(self):
        cleaned, is_trivial = preprocess_post_content("??? !!! .... --- ;;;")
        assert is_trivial is True

    def test_short_content_is_trivial(self):
        cleaned, is_trivial = preprocess_post_content("Too short post")
        assert is_trivial is True
        assert cleaned == "Too short post"


class TestAdaptiveTokenLimits:
    """Verifies adaptive token scaling based on original post length."""

    def test_short_post_token_budget(self):
        assert _get_adaptive_max_tokens(100) == 100
        assert _get_adaptive_max_tokens(250) == 100

    def test_medium_post_token_budget(self):
        assert _get_adaptive_max_tokens(251) == 250
        assert _get_adaptive_max_tokens(800) == 250
        assert _get_adaptive_max_tokens(1000) == 250

    def test_long_post_token_budget(self):
        assert _get_adaptive_max_tokens(1001) == 450
        assert _get_adaptive_max_tokens(4000) == 450


class TestOutputCleaningAndPostProcessing:
    """Verifies removal of LLM meta-preambles and clean sentence boundary truncation."""

    def test_strip_common_llm_preambles(self):
        raw_1 = "Here is a summary of the post: The community iftar will commence at 6:30 PM."
        assert clean_summary_output(raw_1, "") == "The community iftar will commence at 6:30 PM."

        raw_2 = "Summary: Local youth circles will organize weekly Quran recitation sessions."
        assert clean_summary_output(raw_2, "") == "Local youth circles will organize weekly Quran recitation sessions."

        raw_3 = "In summary: Charity drives have reached their milestone goal."
        assert clean_summary_output(raw_3, "") == "Charity drives have reached their milestone goal."

    def test_trim_dangling_sentence_at_boundary(self):
        incomplete = "The weekly class covered Surah Al-Kahf with detailed reflections. Next week we will discuss"
        cleaned = clean_summary_output(incomplete, "")
        assert cleaned == "The weekly class covered Surah Al-Kahf with detailed reflections."


@pytest.mark.asyncio
class TestSummarizationPipelineAndFallback:
    """End-to-end endpoint tests for summarization edge cases and model fallbacks."""

    async def test_empty_or_whitespace_content_rejected_by_validation(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/summarize", json={"user_id": "u1", "post_content": "    "})
            assert resp.status_code == 422

    async def test_short_content_bypasses_llm_gracefully(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.summarize.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                resp = await ac.post("/summarize", json={"user_id": "u1", "post_content": "Short text"})
                assert resp.status_code == 200
                data = resp.json()
                assert data["summary"] == "Short text"
                mock_create.assert_not_called()

    async def test_multilingual_post_summarization(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            mock_choice = MagicMock()
            mock_choice.message.content = "Summary: إِنَّ مَعَ الْعُسْرِ يُسْرًا - Verily with hardship comes ease."
            mock_resp = MagicMock(choices=[mock_choice])

            with patch("app.api.summarize.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_resp

                post = (
                    "Sharing this beautiful reflection today: Always remember the divine promise in Surah Ash-Sharh: "
                    "فَإِنَّ مَعَ الْعُسْرِ يُسْرًا إِنَّ مَعَ الْعُسْرِ يُسْرًا. Truly with every hardship comes ease, "
                    "so let us remain patient and steadfast in our prayers."
                )
                resp = await ac.post("/summarize", json={"user_id": "u_multi", "post_content": post})
                assert resp.status_code == 200
                data = resp.json()
                # Preamble stripped, sacred Arabic verse preserved
                assert "Summary:" not in data["summary"]
                assert "إِنَّ مَعَ الْعُسْرِ يُسْرًا" in data["summary"]

    async def test_summarize_falls_back_on_500_internal_server_error(self):
        """When primary model experiences a 500 InternalServerError, endpoint falls back to openai/gpt-oss-120b."""
        req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        res = httpx.Response(500, request=req, json={"error": {"message": "Internal server error"}})
        server_error = InternalServerError("Groq internal outage", response=res, body=None)

        mock_choice = MagicMock()
        mock_choice.message.content = "Reliable summary produced by fallback 120b model."
        mock_fallback_resp = MagicMock(choices=[mock_choice])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.summarize.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                mock_create.side_effect = [server_error, mock_fallback_resp]

                post = (
                    "Important reminder on time management and productivity: Scheduling daily deep work sessions "
                    "before Fajr and strictly reducing screen time in the evening drastically improves focus and wellbeing."
                )
                resp = await ac.post("/summarize", json={"user_id": "u_fb_500", "post_content": post})
                assert resp.status_code == 200
                data = resp.json()
                assert data["summary"] == "Reliable summary produced by fallback 120b model."

                # Verify both models were invoked in sequence
                assert mock_create.call_count == 2
                assert mock_create.call_args_list[0].kwargs["model"] == settings.GROQ_MODEL
                assert mock_create.call_args_list[1].kwargs["model"] == settings.FALLBACK_GROQ_MODEL

    async def test_summarize_falls_back_on_429_rate_limit(self):
        """When primary model experiences a 429 RateLimitError, endpoint falls back to openai/gpt-oss-120b."""
        req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        res = httpx.Response(429, request=req, json={"error": {"message": "Rate limit reached"}})
        rate_limit_err = RateLimitError("Rate limit exceeded", response=res, body=None)

        mock_choice = MagicMock()
        mock_choice.message.content = "Summary generated after primary rate limit via fallback model."
        mock_fallback_resp = MagicMock(choices=[mock_choice])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.summarize.llm.chat.completions.create", new_callable=AsyncMock) as mock_create:
                mock_create.side_effect = [rate_limit_err, mock_fallback_resp]

                post = (
                    "Weekly community volunteer update: Our charity drive has successfully distributed supplies "
                    "to over 300 families across the valley this past weekend. JazakAllah khair to all volunteers."
                )
                resp = await ac.post("/summarize", json={"user_id": "u_fb_429", "post_content": post})
                assert resp.status_code == 200
                data = resp.json()
                assert data["summary"] == "Summary generated after primary rate limit via fallback model."
                assert mock_create.call_count == 2
                assert mock_create.call_args_list[1].kwargs["model"] == settings.FALLBACK_GROQ_MODEL

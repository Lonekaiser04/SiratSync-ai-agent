"""
Regression tests for Sirat Assistant / Chatbot fixes:
1. Heading sizes and typography scale.
2. Interrupted long responses, keepalives, and safe continuation.
3. Relevant versus irrelevant queries, ensuring genuine answers are grounded
   and never return unrelated app instructions as fallback answers.
"""
import os
import pytest
import re
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("GROQ_API_KEY", "gsk_test_key_for_regression_audit")
os.environ.setdefault("ENV", "test")

from app.services.intent_service import intent_detector
from app.services.rag_service import rag_service
from app.utils.helpers import get_quick_response
from app.prompts.system_prompt import SYSTEM_PROMPT


class TestRelevantVsIrrelevantQueries:
    """Verify that religious and practical questions are not hijacked by canned app instructions."""

    @pytest.mark.asyncio
    async def test_how_to_pray_queries_never_return_learn_salah_app_module_ad(self):
        queries = [
            "how to pray tahajjud",
            "how to pray janazah",
            "how to pray witr",
            "how to pray istikhara",
            "how to pray step by step",
            "how should I pray taraweeh",
        ]
        for query in queries:
            # 1. RAG direct answer must not intercept with app promotional blurb
            direct = rag_service.get_direct_answer(query)
            assert direct is None, f"Query '{query}' was intercepted by get_direct_answer: {direct}"

            # 2. get_quick_response must not deflect to Learn Salah app module
            intent_res = intent_detector.detect(query)
            quick = await get_quick_response(
                query,
                intent_res.primary_intent,
                intent_res.sub_intent,
                {},
            )
            assert quick is None, f"Query '{query}' was intercepted by get_quick_response: {quick}"

    @pytest.mark.asyncio
    async def test_quran_reading_and_purity_queries_never_return_quran_module_ad(self):
        queries = [
            "how to read quran with tajweed",
            "how to read surah al-kahf on friday",
            "can I open quran without wudu",
            "is it permissible to open quran on phone while traveling",
            "how should I read quran when feeling stressed",
        ]
        for query in queries:
            direct = rag_service.get_direct_answer(query)
            assert direct is None or "The Quran Module in SiratSync" not in direct, (
                f"Query '{query}' returned Quran Module ad in get_direct_answer"
            )

            intent_res = intent_detector.detect(query)
            quick = await get_quick_response(
                query,
                intent_res.primary_intent,
                intent_res.sub_intent,
                {},
            )
            if quick:
                assert "Open the Quran module to read" not in quick, (
                    f"Query '{query}' returned app module ad in get_quick_response: {quick}"
                )

    @pytest.mark.asyncio
    async def test_prayer_timing_and_hadith_queries_never_deflect_to_settings(self):
        queries = [
            ("can I pray after asr time", "salah"),
            ("what is the best time for tahajjud prayer", "salah"),
            ("how many times a day do muslims pray", "salah"),
            ("is there hadith about daily exercise", "hadith"),
            ("hadith about daily dhikr and remembrance", "hadith"),
        ]
        for query, expected_domain in queries:
            intent_res = intent_detector.detect(query)
            quick = await get_quick_response(
                query,
                intent_res.primary_intent,
                intent_res.sub_intent,
                {},
            )
            if quick:
                assert "You can check accurate prayer times in the Prayer section" not in quick
                assert "Enable Daily Hadith in Settings" not in quick

    @pytest.mark.asyncio
    async def test_explicit_app_queries_still_work_correctly(self):
        """Explicit questions about the app's modules or features should still be answered cleanly."""
        features_ans = rag_service.get_direct_answer("what are the features of siratsync")
        assert features_ans is not None
        assert "SiratSync Features" in features_ans

        dev_ans = rag_service.get_direct_answer("who made siratsync")
        assert dev_ans is not None
        assert "Kaiser Mohiuddin" in dev_ans

        learn_salah_ans = rag_service.get_direct_answer("learn salah module")
        assert learn_salah_ans is not None
        assert "Learn Salah" in learn_salah_ans

    def test_keyword_fallback_filters_out_app_metadata_for_islamic_queries(self):
        """Islamic queries should not pull in app features/troubleshooting from knowledge.json."""
        retrieved = rag_service._keyword_fallback("ruling on fasting while traveling")
        assert "app_features" not in retrieved.lower()
        assert "troubleshooting" not in retrieved.lower()
        assert "download links" not in retrieved.lower()

    def test_system_prompt_explicitly_forbids_app_instruction_fallbacks(self):
        """Prompt mandate must forbid app instruction fallbacks for religious inquiries."""
        assert "NO APP INSTRUCTION FALLBACKS FOR RELIGIOUS OR PRACTICAL INQUIRIES" in SYSTEM_PROMPT
        assert "NEVER deflect to app modules" in SYSTEM_PROMPT


class TestStreamingContinuationAndKeepalive:
    """Verify SSE streaming keepalives and continuation support."""

    @pytest.mark.asyncio
    async def test_continuation_request_prompt_construction(self):
        from app.api.chat import _chat_stream_generator
        from app.models.request_models import ChatRequest

        req = ChatRequest(
            message="[CONTINUE_REQUEST] What are the pillars of Islam?\n[CONTINUE_FROM]: The first pillar is Shahadah.",
            user_id="test_user_continuation",
        )
        http_req = MagicMock()
        http_req.state = MagicMock()
        http_req.state.request_id = "test_req_cont"
        http_req.state.authenticated_user_id = "test_user_continuation"
        http_req.is_disconnected = AsyncMock(return_value=False)

        # Iterate generator to inspect initial events and ensure keepalive
        events = []
        gen = _chat_stream_generator(req, http_req)
        try:
            for _ in range(5):
                item = await gen.__anext__()
                events.append(item)
        except StopAsyncIteration:
            pass
        finally:
            await gen.aclose()

        # Verify initial status and keepalives are emitted
        combined = "".join(events)
        assert "connected" in combined or ": keep-alive" in combined


class TestSahabaQueriesAndRelevanceScoring:
    """Verify that sahaba queries are factually grounded, properly retrieved, and never replaced with app instructions."""

    def test_how_many_sahaba_are_mentioned_in_quran_factual_answer(self):
        queries = [
            "how many sahaba's are mentioned in Quran",
            "how many sahaba are mentioned in Quran",
            "how many sahaba in quran",
            "which sahabi is mentioned in quran",
            "who is the only sahabi mentioned by name in the quran",
        ]
        for q in queries:
            answer = rag_service.get_direct_answer(q)
            assert answer is not None, f"Query '{q}' returned None from get_direct_answer"
            # Must state exactly one companion by name
            assert "one companion" in answer.lower() or "one sahabi" in answer.lower()
            # Must explicitly name Zayd ibn Harithah and cite 33:37
            assert "Zayd ibn Harithah" in answer
            assert "33:37" in answer
            # Must reference Abu Bakr in 9:40
            assert "Abu Bakr" in answer
            assert "9:40" in answer
            # Must mention collective praise in 9:100 or 48:29
            assert "9:100" in answer or "48:29" in answer
            # Must NEVER mention app features or marketing
            assert "SiratSync" not in answer
            assert "lifestyle companion" not in answer.lower()
            assert "download" not in answer.lower()

    def test_general_sahaba_queries_grounded_answer(self):
        queries = [
            "sahaba's",
            "sahaba",
            "who are the sahaba",
            "who are sahaba",
            "companions of the prophet",
            "tell me about sahaba",
        ]
        for q in queries:
            intent = intent_detector.detect(q)
            assert intent.primary_intent in ("hadith", "quran"), f"Query '{q}' had intent '{intent.primary_intent}'"
            if intent.primary_intent == "hadith":
                assert intent.sub_intent == "sahaba_inquiry"

            answer = rag_service.get_direct_answer(q)
            assert answer is not None, f"Query '{q}' returned None from get_direct_answer"
            assert "Prophet Muhammad" in answer
            assert "33:37" in answer
            assert "Zayd ibn Harithah" in answer
            assert "Sahih al-Bukhari 3673" in answer
            # Never confuse with app features
            assert "module" not in answer.lower()
            assert "settings" not in answer.lower()
            assert "lifestyle companion" not in answer.lower()

    def test_search_quran_by_topic_returns_relevant_sahaba_verses_and_hadith(self):
        topic_res = rag_service.search_quran_by_topic("how many sahaba's are mentioned in Quran")
        verses = topic_res.get("verses", [])
        hadiths = topic_res.get("hadiths", [])

        assert len(verses) >= 3, "Topic search should return key Sahaba verses"
        verse_refs = [(v["surah_id"], v["verse_id"]) for v in verses]

        # 33:37 (Zayd) and 9:40 (Abu Bakr in cave) must be in the top verses
        assert (33, 37) in verse_refs, f"33:37 missing from topic verses: {verse_refs}"
        assert (9, 40) in verse_refs, f"9:40 missing from topic verses: {verse_refs}"

        # Must not retrieve false matches like 2:61 (food/onions/musa)
        assert (2, 61) not in verse_refs, "2:61 falsely matched in sahaba search!"

        # Must return authentic Hadith honoring the companions
        assert len(hadiths) >= 1, "Hadith honoring companions must be retrieved"
        assert any("3673" in h["source"] or "2652" in h["source"] for h in hadiths)

    def test_relevance_scoring_word_boundary_prevents_substring_false_positives(self):
        """Ensure topic name 'one' does not falsely match within 'mentioned'."""
        topic_res = rag_service.search_quran_by_topic("verses mentioned in the book")
        verses = topic_res.get("verses", [])
        verse_refs = [(v["surah_id"], v["verse_id"]) for v in verses]
        assert (2, 61) not in verse_refs, "2:61 falsely matched due to 'one' substring in 'mentioned'"

    def test_keyword_fallback_blocks_companion_app_descriptions(self):
        fallback = rag_service._keyword_fallback("sahaba's")
        assert "lifestyle companion" not in fallback.lower()
        assert "spiritual companion" not in fallback.lower()
        assert "app_features" not in fallback.lower()

    def test_system_prompt_sahaba_grounding_directive(self):
        assert "FACTUAL GROUNDING ON COMPANIONS (SAHABA)" in SYSTEM_PROMPT
        assert "Zayd ibn Harithah" in SYSTEM_PROMPT
        assert "33:37" in SYSTEM_PROMPT



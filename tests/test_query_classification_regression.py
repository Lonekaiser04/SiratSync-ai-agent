import pytest
import re
from app.utils.helpers import is_time_or_non_verse_reference, get_quick_response
from app.api.chat import _is_verse_or_surah_query
from app.services.rag_service import rag_service

class TestQueryClassificationRegression:
    """Regression tests verifying relevant vs. irrelevant query classification,
    preventing secular times and unrelated terms from matching Islamic Lookups."""

    def test_features_of_python_not_intercepted_as_siratsync_features(self):
        query = "What are the key features of Python 3.12?"
        direct = rag_service.get_direct_answer(query)
        assert direct is None or "Python" in direct

    def test_app_features_explicit_query_returns_features(self):
        query = "what are the features"
        direct = rag_service.get_direct_answer(query)
        assert direct is not None
        assert "SiratSync" in direct or "Quran" in direct

    def test_time_expression_meeting_at_230_pm_not_verse(self):
        query = "Can you meet me at 2:30 pm tomorrow?"
        m = re.search(r'\b([1-9]|[1-9]\d|1[01]\d|114):([1-9]\d{0,2})\b', query.lower())
        assert m is not None
        assert is_time_or_non_verse_reference(query, m) is True
        assert _is_verse_or_surah_query(query.lower()) is False

    def test_time_expression_train_at_315_not_verse(self):
        query = "The flight is scheduled at 3:15"
        m = re.search(r'\b([1-9]|[1-9]\d|1[01]\d|114):([1-9]\d{0,2})\b', query.lower())
        assert m is not None
        assert is_time_or_non_verse_reference(query, m) is True
        assert _is_verse_or_surah_query(query.lower()) is False

    def test_genuine_verse_reference_detected(self):
        queries = ["2:255", "Surah 2:30", "read 2:153", "what does 112:1 say?"]
        for q in queries:
            assert _is_verse_or_surah_query(q.lower()) is True

    @pytest.mark.asyncio
    async def test_git_offline_query_not_intercepted(self):
        response = await get_quick_response(
            message="How do I use git offline?",
            intent="general",
            sub_intent=None,
            user_profile={},
        )
        assert response is None

    @pytest.mark.asyncio
    async def test_community_college_query_not_intercepted(self):
        response = await get_quick_response(
            message="What is the tuition fee at a community college?",
            intent="general",
            sub_intent=None,
            user_profile={},
        )
        assert response is None

    def test_rights_of_us_citizen_not_quran_topic(self):
        query = "what are the rights of a US citizen under the constitution?"
        assert rag_service._is_quran_topic_query(query.lower()) is False

    def test_rights_of_parents_in_islam_is_quran_topic(self):
        query = "what are the rights of parents in islam?"
        assert rag_service._is_quran_topic_query(query.lower()) is True

    def test_unrelated_science_query_does_not_return_spurious_rag_category(self):
        query = "explain how photosynthesis works in green plants"
        direct = rag_service.get_direct_answer(query)
        assert direct is None
        fallback = rag_service._keyword_fallback(query.lower())
        # Should not return app features or community items with 0 word matches
        assert "SiratSync" not in fallback

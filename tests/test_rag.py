import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from app.services.rag_service import RAGKnowledge, _expand_query, _meaningful_words


@pytest.fixture
def rag():
    """Create RAGKnowledge instance pointing to test data"""
    return RAGKnowledge(
        kb_path="knowledge.json",
        quran_index_path="quran_indexed_final.json"
    )


class TestHelpers:
    def test_expand_query_transliteration(self):
        assert "patience" in _expand_query("sabr")
        assert "gratitude" in _expand_query("shukr")
    
    def test_expand_query_no_match(self):
        result = _expand_query("hello")
        assert result == "hello"
    
    def test_meaningful_words_filters_stopwords(self):
        words = _meaningful_words("what does the quran say about patience")
        assert "what" not in words
        assert "the" not in words
        assert "patience" in words


class TestDirectAnswers:
    def test_developer_query(self, rag):
        result = rag.get_direct_answer("who made siratsync")
        assert result is not None
        assert "Kaiser" in result
    
    def test_features_query(self, rag):
        result = rag.get_direct_answer("what are the features")
        assert result is not None
        assert "Quran" in result or "Prayer" in result
    
    def test_non_matching_query(self, rag):
        result = rag.get_direct_answer("random text xyz123")
        assert result is None


class TestSurahLookup:
    def test_get_surah_by_exact_name(self, rag):
        surah = rag.get_surah_by_name("al fatihah")
        assert surah is not None
        assert surah.get("id") == 1
    
    def test_get_surah_by_number(self, rag):
        surah = rag.get_surah_by_id(1)
        assert surah is not None
        assert "fatihah" in surah.get("name_en", "").lower()
    
    def test_get_surah_invalid(self, rag):
        assert rag.get_surah_by_name("xyz none existent") is None
        assert rag.get_surah_by_id(999) is None
    
    def test_spelling_normalization(self, rag):
        # Test common misspellings
        surah = rag.get_surah_by_name("yaseen")
        assert surah is not None


class TestVerseRetrieval:
    def test_get_verse_by_reference(self, rag):
        verse = rag.get_verse_by_reference(1, 1)
        assert verse is not None
        assert verse["surah_id"] == 1
        assert verse["verse_id"] == 1
        assert len(verse["arabic"]) > 0
        assert len(verse["english"]) > 0
    
    def test_get_verse_invalid(self, rag):
        assert rag.get_verse_by_reference(114, 999) is None
        assert rag.get_verse_by_reference(999, 1) is None


class TestRetrieve:
    def test_retrieve_surah_query(self, rag):
        result = rag.retrieve("tell me about surah ikhlas")
        assert result is not None
        assert "couldn't find" not in result.lower()
    
    def test_retrieve_verse_reference(self, rag):
        result = rag.retrieve("show me 2:255")
        assert result is not None
        assert "2:255" in result or "255" in result
    
    def test_retrieve_topic(self, rag):
        result = rag.retrieve("what does quran say about patience")
        assert result is not None
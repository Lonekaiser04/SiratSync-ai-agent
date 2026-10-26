import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from app.services.rag_service import RAGKnowledge


@pytest.fixture
def rag():
    return RAGKnowledge(
        kb_path="knowledge.json",
        quran_index_path="quran_indexed_final.json"
    )


class TestQuranTopicSearch:
    def test_search_by_topic_patience(self, rag):
        result = rag.search_quran_by_topic("patience")
        assert "verses" in result
        assert "surahs" in result
        assert len(result["verses"]) > 0 or len(result["surahs"]) > 0
    
    def test_search_known_verse_mapping(self, rag):
        result = rag.search_quran_by_topic("rights of sisters")
        verses = result.get("verses", [])
        assert len(verses) > 0
        # Should have high relevance scores
        assert any(v.get("relevance_score", 0) >= 90 for v in verses)
    
    def test_search_unknown_topic(self, rag):
        result = rag.search_quran_by_topic("xyz random nonsense")
        assert result["verses"] == []
        assert result["surahs"] == []


class TestQuranStats:
    def test_total_quran_stats(self, rag):
        result = rag._handle_stats_query("total quran statistics")
        assert result is not None
        assert "114" in result
        assert "6,236" in result or "6236" in result
    
    def test_longest_surah(self, rag):
        result = rag._handle_stats_query("longest surah")
        assert result is not None
        assert "baqarah" in result.lower()
    
    def test_longest_verse(self, rag):
        result = rag._handle_stats_query("longest verse")
        assert result is not None
        assert "282" in result


class TestJuzQueries:
    def test_juz_query(self, rag):
        result = rag._handle_juz_query("juz 30")
        assert result is not None
        assert "30" in result
    
    def test_juz_para_query(self, rag):
        result = rag._handle_juz_query("para 1")
        assert result is not None


class TestSimilarAyahs:
    def test_get_similar_ayahs(self, rag):
        similar = rag.get_similar_ayahs(2, 255, top_n=3, min_score=30)
        assert isinstance(similar, list)
    
    def test_similar_ayahs_invalid(self, rag):
        similar = rag.get_similar_ayahs(999, 999)
        assert similar == []


class TestSurahSummary:
    def test_get_surah_summary(self, rag):
        summary = rag.get_surah_summary("al fatihah")
        assert summary is not None
        assert summary["id"] == 1
        assert len(summary["main_topics"]) > 0
        assert summary["verse_count"] == 7
    
    def test_surah_summary_invalid(self, rag):
        assert rag.get_surah_summary("nonexistent") is None
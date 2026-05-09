# -*- coding: utf-8 -*-
"""
SiratSync - Complete Test Suite
Run this file directly: python tests/run_all_tests.py
"""

import sys
import os

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set test environment variables BEFORE any imports
os.environ["GROQ_API_KEY"] = "test-key-for-testing-only"
os.environ["REDIS_URL"] = ""  # Force memory fallback, skip Redis

import json
import time
from datetime import datetime


# ═══════════════════════════════════════════════════════════════════
# TEST RUNNER CLASS
# ═══════════════════════════════════════════════════════════════════

class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.start_time = None
        
    def run(self, name, func):
        try:
            func()
            self.passed += 1
            print(f"  ✅ PASSED - {name}")
            return True
        except AssertionError as e:
            self.failed += 1
            self.errors.append((name, str(e)))
            print(f"  ❌ FAILED - {name}")
            print(f"      Reason: {e}")
            return False
        except Exception as e:
            self.failed += 1
            self.errors.append((name, str(e)))
            print(f"  💥 ERROR - {name}")
            print(f"      {type(e).__name__}: {e}")
            return False
    
    def section(self, title):
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}")
    
    def summary(self):
        total = self.passed + self.failed
        duration = time.time() - self.start_time if self.start_time else 0
        print(f"\n{'='*60}")
        print(f"  TEST RESULTS SUMMARY")
        print(f"{'='*60}")
        print(f"  Total Tests:  {total}")
        print(f"  ✅ Passed:    {self.passed}")
        print(f"  ❌ Failed:    {self.failed}")
        print(f"  ⏱️  Duration:  {duration:.2f}s")
        print(f"  Success Rate: {(self.passed/total*100) if total > 0 else 0:.1f}%")
        print(f"{'='*60}\n")
        
        if self.errors:
            print(f"  FAILURES DETAIL:")
            for i, (name, error) in enumerate(self.errors, 1):
                print(f"  {i}. {name}")
                print(f"     {error}\n")


# ═══════════════════════════════════════════════════════════════════
# RAG SERVICE TESTS
# ═══════════════════════════════════════════════════════════════════

def test_rag_services(runner):
    runner.section("RAG SERVICE TESTS")
    
    from app.services.rag_service import RAGKnowledge, _expand_query, _meaningful_words
    
    # Create RAG instance
    rag = RAGKnowledge(
        kb_path="knowledge.json",
        quran_index_path="quran_indexed_final.json"
    )
    
    # Helper function tests
    def test_transliteration_expansion():
        result = _expand_query("sabr")
        assert "patience" in result, "sabr should expand to patience"
    
    def test_meaningful_words_filters():
        words = _meaningful_words("what does the quran say about patience")
        assert "what" not in words, "stopword 'what' should be filtered"
        assert "the" not in words, "stopword 'the' should be filtered"
        assert "patience" in words, "'patience' should remain"
    
    def test_direct_answer_developer():
        result = rag.get_direct_answer("who made siratsync")
        assert result is not None, "Should return developer info"
        assert "Kaiser" in result, "Should mention Kaiser"
    
    def test_direct_answer_features():
        result = rag.get_direct_answer("what are the features")
        assert result is not None, "Should return features list"
        assert len(result) > 50, "Features response should be substantial"
    
    def test_direct_answer_none():
        result = rag.get_direct_answer("random xyz abc 12345")
        assert result is None, "Should return None for unknown query"
    
    def test_surah_by_name():
        surah = rag.get_surah_by_name("al fatihah")
        assert surah is not None, "Should find Al-Fatihah"
        assert surah.get("id") == 1, "Al-Fatihah should be surah 1"
    
    def test_surah_by_number():
        surah = rag.get_surah_by_id(1)
        assert surah is not None, "Should find surah 1"
        assert "fatihah" in surah.get("name_en", "").lower(), "Should be Al-Fatihah"
    
    def test_surah_invalid():
        assert rag.get_surah_by_name("xyz no exist") is None, "Invalid surah should return None"
        assert rag.get_surah_by_id(999) is None, "Invalid surah ID should return None"
    
    def test_spelling_normalization():
        surah = rag.get_surah_by_name("yaseen")  # Common misspelling
        assert surah is not None, "Should find Yasin by common misspelling"
    
    def test_verse_by_reference():
        verse = rag.get_verse_by_reference(1, 1)
        assert verse is not None, "Should find verse 1:1"
        assert verse["surah_id"] == 1
        assert verse["verse_id"] == 1
        assert len(verse["arabic"]) > 0, "Should have Arabic text"
        assert len(verse["english"]) > 0, "Should have English text"
    
    def test_verse_invalid():
        assert rag.get_verse_by_reference(114, 999) is None, "Invalid verse should be None"
        assert rag.get_verse_by_reference(999, 1) is None, "Invalid surah should be None"
    
    def test_retrieve_surah():
        result = rag.retrieve("tell me about surah ikhlas")
        assert result is not None, "Should retrieve surah info"
        assert "couldn't find" not in result.lower(), "Should find the surah"
    
    def test_retrieve_verse_ref():
        result = rag.retrieve("show me 2:255")
        assert result is not None, "Should retrieve verse"
        assert "255" in result, "Should contain verse number"
    
    def test_surah_summary():
        summary = rag.get_surah_summary("al fatihah")
        assert summary is not None, "Should get summary"
        assert summary["id"] == 1, "Should be surah 1"
        assert summary["verse_count"] == 7, "Al-Fatihah has 7 verses"
        assert len(summary["main_topics"]) > 0, "Should have main topics"
    
    def test_topic_search():
        result = rag.search_quran_by_topic("patience")
        assert "verses" in result, "Should have verses key"
        assert "surahs" in result, "Should have surahs key"
        assert len(result["verses"]) > 0 or len(result["surahs"]) > 0, "Should find results"
    
    def test_known_verse_mapping():
        result = rag.search_quran_by_topic("rights of sisters")
        verses = result.get("verses", [])
        assert len(verses) > 0, "Should find verses about sisters' rights"
    
    def test_quran_stats():
        result = rag._handle_stats_query("total quran statistics")
        assert result is not None, "Should return stats"
        assert "114" in result, "Should mention 114 surahs"
    
    def test_longest_surah():
        result = rag._handle_stats_query("longest surah")
        assert result is not None, "Should return longest surah"
        assert "baqarah" in result.lower(), "Longest surah should be Al-Baqarah"
    
    def test_longest_verse():
        result = rag._handle_stats_query("longest verse")
        assert result is not None, "Should return longest verse"
        assert "282" in result, "Longest verse should be 2:282"
    
    def test_juz_query():
        result = rag._handle_juz_query("juz 30")
        assert result is not None, "Should return Juz 30 info"
        assert "30" in result, "Should mention Juz 30"
    
    def test_similar_ayahs():
        similar = rag.get_similar_ayahs(2, 255, top_n=3, min_score=30)
        assert isinstance(similar, list), "Should return a list"
    
    def test_list_categories():
        categories = rag.list_categories()
        assert isinstance(categories, list), "Should return list"
        assert len(categories) > 0, "Should have categories"
    
    # Run all RAG tests
    tests = [
        ("Transliteration expansion", test_transliteration_expansion),
        ("Meaningful words filter", test_meaningful_words_filters),
        ("Direct answer - developer", test_direct_answer_developer),
        ("Direct answer - features", test_direct_answer_features),
        ("Direct answer - no match", test_direct_answer_none),
        ("Surah by name", test_surah_by_name),
        ("Surah by number", test_surah_by_number),
        ("Surah invalid lookup", test_surah_invalid),
        ("Spelling normalization", test_spelling_normalization),
        ("Verse by reference", test_verse_by_reference),
        ("Verse invalid", test_verse_invalid),
        ("Retrieve surah query", test_retrieve_surah),
        ("Retrieve verse reference", test_retrieve_verse_ref),
        ("Surah summary", test_surah_summary),
        ("Topic search", test_topic_search),
        ("Known verse mapping", test_known_verse_mapping),
        ("Quran statistics", test_quran_stats),
        ("Longest surah", test_longest_surah),
        ("Longest verse", test_longest_verse),
        ("Juz query", test_juz_query),
        ("Similar ayahs", test_similar_ayahs),
        ("List categories", test_list_categories),
    ]
    
    for name, test_func in tests:
        runner.run(name, test_func)


# ═══════════════════════════════════════════════════════════════════
# API ENDPOINT TESTS
# ═══════════════════════════════════════════════════════════════════

def test_api_endpoints(runner):
    runner.section("API ENDPOINT TESTS")
    
    from fastapi.testclient import TestClient
    from app.main import app
    
    client = TestClient(app)
    
    def test_health_get():
        response = client.get("/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
    
    def test_health_head():
        response = client.head("/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    def test_chat_greeting():
        payload = {"user_id": "test_user_1", "message": "Assalamu alaikum"}
        response = client.post("/chat", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "reply" in data, "Response should have 'reply'"
        assert "intent" in data, "Response should have 'intent'"
        assert "sentiment" in data, "Response should have 'sentiment'"
        assert "actions" in data, "Response should have 'actions'"
        assert "suggestions" in data, "Response should have 'suggestions'"
        assert "timestamp" in data, "Response should have 'timestamp'"
    
    def test_chat_quran_query():
        payload = {"user_id": "test_user_2", "message": "show me verse 2:255"}
        response = client.post("/chat", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert len(data["reply"]) > 0, "Reply should not be empty"
    
    def test_chat_features_query():
        payload = {"user_id": "test_user_3", "message": "What can you do?"}
        response = client.post("/chat", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert len(data["reply"]) > 0, "Reply should not be empty"
    
    def test_chat_empty_message():
        payload = {"user_id": "test_user_4", "message": ""}
        response = client.post("/chat", json=payload)
        assert response.status_code == 422, f"Expected 422 for empty message, got {response.status_code}"
    
    def test_chat_too_long():
        payload = {"user_id": "test_user_5", "message": "x" * 2001}
        response = client.post("/chat", json=payload)
        assert response.status_code == 422, f"Expected 422 for long message, got {response.status_code}"
    
    def test_chat_empty_user_id():
        payload = {"user_id": "", "message": "hello"}
        response = client.post("/chat", json=payload)
        assert response.status_code == 422, f"Expected 422 for empty user_id, got {response.status_code}"
    
    def test_summarize_short():
        payload = {"user_id": "test_user_6", "post_content": "Short post"}
        response = client.post("/summarize", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["summary"] == "Short post"
    
    def test_user_summary():
        response = client.get("/user/test_user_1/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["user_id"] == "test_user_1"
        assert "profile" in data
    
    def test_clear_session():
        response = client.delete("/user/test_user_1/session")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "success"
    
    def test_response_structure():
        payload = {"user_id": "test_user_7", "message": "What is SiratSync?"}
        response = client.post("/chat", json=payload)
        assert response.status_code == 200
        data = response.json()
        required = ["reply", "intent", "sentiment", "actions", "suggestions", "timestamp"]
        for field in required:
            assert field in data, f"Missing field: {field}"
        assert isinstance(data["reply"], str)
        assert isinstance(data["actions"], dict)
        assert isinstance(data["suggestions"], list)
    
    tests = [
        ("Health GET endpoint", test_health_get),
        ("Health HEAD endpoint", test_health_head),
        ("Chat - greeting", test_chat_greeting),
        ("Chat - Quran verse query", test_chat_quran_query),
        ("Chat - features query", test_chat_features_query),
        ("Chat - empty message validation", test_chat_empty_message),
        ("Chat - too long message validation", test_chat_too_long),
        ("Chat - empty user_id validation", test_chat_empty_user_id),
        ("Summarize - short content", test_summarize_short),
        ("User - get summary", test_user_summary),
        ("User - clear session", test_clear_session),
        ("Chat - response structure", test_response_structure),
    ]
    
    for name, test_func in tests:
        runner.run(name, test_func)


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║         SiratSync AI - Complete Test Suite              ║")
    print("║                  Version 2.0                            ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    
    runner = TestRunner()
    runner.start_time = time.time()
    
    # Run RAG service tests
    test_rag_services(runner)
    
    # Run API endpoint tests
    test_api_endpoints(runner)
    
    # Print summary
    runner.summary()
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.request_models import ChatRequest, SummarizeRequest

client = TestClient(app)


class TestHealthEndpoint:
    def test_health_check(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "components" in data
    
    def test_health_head(self):
        response = client.head("/health")
        assert response.status_code == 200


class TestChatEndpoint:
    def test_chat_greeting(self):
        payload = {
            "user_id": "test_user_1",
            "message": "Assalamu alaikum",
        }
        response = client.post("/chat", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "reply" in data
        assert "intent" in data
        assert "sentiment" in data
        assert "actions" in data
        assert "suggestions" in data
        assert "timestamp" in data
    
    def test_chat_with_context(self):
        payload = {
            "user_id": "test_user_2",
            "message": "show me verse 2:255",
            "user_name": "TestUser",
            "context": "previous discussion about Quran"
        }
        response = client.post("/chat", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert len(data["reply"]) > 0
    
    def test_chat_empty_message(self):
        payload = {
            "user_id": "test_user_3",
            "message": ""
        }
        response = client.post("/chat", json=payload)
        assert response.status_code == 422  # Validation error
    
    def test_chat_too_long_message(self):
        payload = {
            "user_id": "test_user_4",
            "message": "x" * 2001
        }
        response = client.post("/chat", json=payload)
        assert response.status_code == 422
    
    def test_chat_invalid_user_id(self):
        payload = {
            "user_id": "",
            "message": "hello"
        }
        response = client.post("/chat", json=payload)
        assert response.status_code == 422


class TestSummarizeEndpoint:
    def test_summarize_short_content(self):
        payload = {
            "user_id": "test_user_5",
            "post_content": "Short post"
        }
        response = client.post("/summarize", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["summary"] == "Short post"
        assert data["original_length"] == data["summary_length"]
    
    def test_summarize_long_content(self):
        payload = {
            "user_id": "test_user_6",
            "post_content": (
                "The Quran teaches us patience and perseverance in times of difficulty. "
                "Allah says in Surah Al-Baqarah verse 155: 'And We will surely test you "
                "with something of fear and hunger and a loss of wealth and lives and fruits, "
                "but give good tidings to the patient.' This verse reminds us that tests are "
                "part of life and patience is rewarded. The believers are those who, when "
                "disaster strikes them, say 'Indeed we belong to Allah, and indeed to Him "
                "we will return.'"
            )
        }
        response = client.post("/summarize", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert len(data["summary"]) > 0
        assert data["original_length"] > 30
        assert data["summary_length"] < data["original_length"]


class TestUserEndpoints:
    def test_get_user_summary(self):
        response = client.get("/user/test_user_1/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "test_user_1"
        assert "profile" in data
        assert "session" in data
    
    def test_clear_user_session(self):
        response = client.delete("/user/test_user_1/session")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"


class TestResponseModel:
    def test_chat_response_structure(self):
        payload = {
            "user_id": "test_user_7",
            "message": "What is SiratSync?"
        }
        response = client.post("/chat", json=payload)
        data = response.json()
        
        required_fields = ["reply", "intent", "sentiment", "actions", "suggestions", "timestamp"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        assert isinstance(data["reply"], str)
        assert isinstance(data["intent"], str)
        assert isinstance(data["sentiment"], str)
        assert isinstance(data["actions"], dict)
        assert isinstance(data["suggestions"], list)
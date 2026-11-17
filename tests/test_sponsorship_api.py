import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings

client = TestClient(app)


def test_public_get_sponsorship_config():
    """Verify /sponsorship/config is publicly accessible without authentication."""
    response = client.get("/sponsorship/config")
    assert response.status_code == 200
    data = response.json()
    assert "is_active" in data
    assert "sponsor_name" in data
    assert "target_url" in data


def test_record_sponsorship_click_valid():
    """Verify valid click recording for home_banner."""
    payload = {
        "placement": "home_banner",
        "sponsor_id": "mathobah",
        "device_id": "test-device-uuid-12345",
        "client_timestamp": "2026-11-17T12:00:00Z",
        "platform": "android",
    }
    response = client.post("/sponsorship/click", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("recorded", "debounced")
    assert data["placement"] == "home_banner"


def test_record_sponsorship_click_invalid_placement():
    """Verify that invalid placements are rejected with 422 Unprocessable Entity."""
    payload = {
        "placement": "invalid_placement_name",
        "sponsor_id": "mathobah",
        "device_id": "test-device-uuid-12345",
    }
    response = client.post("/sponsorship/click", json=payload)
    assert response.status_code == 422


def test_record_sponsorship_click_invalid_device_id():
    """Verify that device_id shorter than 8 characters is rejected with 422."""
    payload = {
        "placement": "hadith_attribution",
        "sponsor_id": "mathobah",
        "device_id": "short",
    }
    response = client.post("/sponsorship/click", json=payload)
    assert response.status_code == 422


def test_record_sponsorship_click_debouncing():
    """Verify that rapid identical clicks from the same device are debounced."""
    unique_device = "rapid-tap-device-99999"
    payload = {
        "placement": "verse_attribution",
        "sponsor_id": "mathobah",
        "device_id": unique_device,
    }
    # First click
    res1 = client.post("/sponsorship/click", json=payload)
    assert res1.status_code == 200

    # Immediate second click
    res2 = client.post("/sponsorship/click", json=payload)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "debounced"
    assert data2["recorded"] is False


def test_admin_endpoints_require_auth():
    """Verify /sponsorship/analytics and /sponsorship/config POST require admin auth."""
    # Analytics without auth
    res_analytics = client.get("/sponsorship/analytics")
    assert res_analytics.status_code == 401

    # Config update without auth
    res_config = client.post("/sponsorship/config", json={"is_active": True})
    assert res_config.status_code == 401


def test_admin_endpoints_with_internal_api_key():
    """Verify /sponsorship/analytics and /sponsorship/config succeed with X-API-Key."""
    headers = {"X-API-Key": settings.INTERNAL_API_KEY}

    # Analytics
    res_analytics = client.get("/sponsorship/analytics?sponsor_id=mathobah&daily_limit=5", headers=headers)
    assert res_analytics.status_code == 200
    data = res_analytics.json()
    assert "sponsor_id" in data
    assert "summary" in data
    assert "daily" in data

    # Config update
    update_payload = {
        "is_active": True,
        "sponsor_name": "Mathobah",
        "target_url": "https://mathoba.com/app/",
    }
    res_config = client.post("/sponsorship/config", json=update_payload, headers=headers)
    assert res_config.status_code == 200
    config_data = res_config.json()
    assert config_data["sponsor_name"] == "Mathobah"
    assert config_data["is_active"] is True

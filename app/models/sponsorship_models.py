"""
Pydantic data models for remote sponsorship endpoints, validations, and responses.
"""
from __future__ import annotations

import re
from typing import Any
from pydantic import BaseModel, Field, field_validator

VALID_PLACEMENTS = frozenset({"home_banner", "hadith_attribution", "verse_attribution"})
_SLUG_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


class SponsorshipClickRequest(BaseModel):
    """Payload sent by mobile/web clients when a user taps a sponsorship placement."""

    placement: str = Field(..., description="Placement identifier: home_banner, hadith_attribution, or verse_attribution")
    sponsor_id: str = Field(default="mathobah", max_length=64, description="Sponsor campaign identifier")
    device_id: str = Field(..., min_length=8, max_length=128, description="Privacy-preserving anonymous device UUID")
    client_timestamp: str | None = Field(default=None, max_length=64, description="Client device timestamp")
    platform: str | None = Field(default="android", max_length=32, description="Client OS platform")

    @field_validator("placement")
    @classmethod
    def validate_placement(cls, v: str) -> str:
        v_clean = v.strip().lower()
        if v_clean not in VALID_PLACEMENTS:
            raise ValueError(
                f"Invalid placement '{v}'. Must be one of: {', '.join(sorted(VALID_PLACEMENTS))}"
            )
        return v_clean

    @field_validator("sponsor_id")
    @classmethod
    def validate_sponsor_id(cls, v: str) -> str:
        v_clean = v.strip().lower()
        if not v_clean or not _SLUG_RE.match(v_clean):
            return "mathobah"
        return v_clean

    @field_validator("device_id")
    @classmethod
    def validate_device_id(cls, v: str) -> str:
        v_clean = v.strip()
        if len(v_clean) < 8:
            raise ValueError("device_id must be at least 8 characters long")
        return v_clean


class SponsorshipClickResponse(BaseModel):
    """Response returned upon recording a sponsorship click."""

    status: str
    recorded: bool
    click_id: str | None = None
    placement: str | None = None
    message: str | None = None


class SponsorshipConfigUpdate(BaseModel):
    """Administrative update payload for app_config/sponsorship."""

    is_active: bool | None = None
    sponsor_name: str | None = Field(default=None, max_length=100)
    tagline: str | None = Field(default=None, max_length=300)
    banner_url: str | None = Field(default=None, max_length=500)
    banner_url_dark: str | None = Field(default=None, max_length=500)
    target_url: str | None = Field(default=None, max_length=500)
    promo_code: str | None = Field(default=None, max_length=50)

    @field_validator("target_url")
    @classmethod
    def validate_target_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v_clean = v.strip()
        if not v_clean:
            return None
        if not (v_clean.startswith("http://") or v_clean.startswith("https://")):
            raise ValueError("target_url must start with http:// or https://")
        return v_clean


class SponsorshipConfigResponse(BaseModel):
    """Configuration model returned to clients."""

    is_active: bool
    sponsor_name: str
    tagline: str
    banner_url: str
    banner_url_dark: str | None = None
    target_url: str
    promo_code: str
    updated_at: str | None = None


class SponsorshipAnalyticsResponse(BaseModel):
    """Aggregated analytics response for administrators."""

    sponsor_id: str
    summary: dict[str, Any]
    daily: list[dict[str, Any]]

"""
FastAPI endpoints for Remote Sponsorship Integration:
- POST /sponsorship/click: Records placement clicks with rate limiting & deduplication.
- GET  /sponsorship/config: Public retrieval of active sponsorship configuration.
- GET  /sponsorship/analytics: Admin-only retrieval of aggregated click analytics.
- POST /sponsorship/config: Admin-only remote updating of sponsorship configuration.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.core.security import require_admin_auth, verify_firebase_token
from app.models.sponsorship_models import (
    SponsorshipAnalyticsResponse,
    SponsorshipClickRequest,
    SponsorshipClickResponse,
    SponsorshipConfigResponse,
    SponsorshipConfigUpdate,
)
from app.services.sponsorship_backend_service import sponsorship_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sponsorship", tags=["sponsorship"])


@router.post(
    "/click",
    response_model=SponsorshipClickResponse,
    summary="Record sponsorship placement click",
    description="Records a valid click event from Home banner or Ibadah attribution. Available to anonymous and signed-in users.",
)
async def record_sponsorship_click(
    payload: SponsorshipClickRequest,
    authorization: str | None = Header(default=None),
) -> SponsorshipClickResponse:
    # 1. Check duplicate tap / burst rate limit
    is_blocked, reason = await sponsorship_service.is_duplicate_or_rate_limited(
        device_id=payload.device_id,
        placement=payload.placement,
    )

    if is_blocked:
        if reason == "debounced":
            return SponsorshipClickResponse(
                status="debounced",
                recorded=False,
                placement=payload.placement,
                message="Duplicate tap debounced within cooldown window",
            )
        elif reason == "rate_limited":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Click rate limit exceeded. Please wait before tapping again.",
            )

    # 2. Extract verified user UID if token was supplied
    user_id = verify_firebase_token(authorization) if authorization else None

    # 3. Record atomically in Firestore
    try:
        result = await sponsorship_service.record_click(
            placement=payload.placement,
            sponsor_id=payload.sponsor_id,
            device_id=payload.device_id,
            client_timestamp=payload.client_timestamp,
            platform=payload.platform,
            user_id=user_id,
        )
        return SponsorshipClickResponse(
            status="recorded",
            recorded=True,
            click_id=result.get("click_id"),
            placement=payload.placement,
            message="Click successfully recorded",
        )
    except Exception as e:
        logger.error("Failed to record sponsorship click: %s", e, exc_info=True)
        # Never fail aggressively for the user
        return SponsorshipClickResponse(
            status="fallback",
            recorded=False,
            placement=payload.placement,
            message=f"Failed to record analytics: {e}",
        )


@router.get(
    "/config",
    response_model=SponsorshipConfigResponse,
    summary="Get active sponsorship configuration",
    description="Returns central sponsorship configuration from Firestore. Publicly accessible without authentication.",
)
async def get_sponsorship_config() -> SponsorshipConfigResponse:
    try:
        data = await sponsorship_service.get_config()
        return SponsorshipConfigResponse(
            is_active=data.get("is_active", False),
            sponsor_name=data.get("sponsor_name", "Mathobah"),
            tagline=data.get("tagline", ""),
            banner_url=data.get("banner_url", "assets/images/ad_mathuba_light.jpeg"),
            banner_url_dark=data.get("banner_url_dark", "assets/images/ad_mathuba_dark.jpeg"),
            target_url=data.get("target_url", "https://mathoba.com/app/"),
            promo_code=data.get("promo_code", "SIRATSYNC"),
            updated_at=data.get("updated_at"),
        )
    except Exception as e:
        logger.error("Failed to retrieve sponsorship config: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve sponsorship configuration.",
        ) from e


@router.post(
    "/config",
    response_model=SponsorshipConfigResponse,
    summary="Update sponsorship configuration (Admin only)",
    description="Updates remote sponsorship configuration. Strictly requires verified administrative credentials.",
)
async def update_sponsorship_config(
    payload: SponsorshipConfigUpdate,
    admin_auth: dict[str, Any] = Depends(require_admin_auth),
) -> SponsorshipConfigResponse:
    try:
        update_data = payload.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No configuration fields provided for update.",
            )

        updated = await sponsorship_service.update_config(
            update_fields=update_data,
            updated_by=admin_auth.get("uid"),
        )

        return SponsorshipConfigResponse(
            is_active=updated.get("is_active", False),
            sponsor_name=updated.get("sponsor_name", "Mathobah"),
            tagline=updated.get("tagline", ""),
            banner_url=updated.get("banner_url", "assets/images/ad_mathuba_light.jpeg"),
            banner_url_dark=updated.get("banner_url_dark", "assets/images/ad_mathuba_dark.jpeg"),
            target_url=updated.get("target_url", "https://mathoba.com/app/"),
            promo_code=updated.get("promo_code", "SIRATSYNC"),
            updated_at=updated.get("updated_at"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update sponsorship config: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update sponsorship configuration.",
        ) from e


@router.get(
    "/analytics",
    response_model=SponsorshipAnalyticsResponse,
    summary="Get aggregated sponsorship analytics (Admin only)",
    description="Retrieves lifetime totals, placement breakdown, and daily stats. Strictly requires verified administrative credentials.",
)
async def get_sponsorship_analytics(
    sponsor_id: str = Query(default="mathobah", max_length=64),
    daily_limit: int = Query(default=30, ge=1, le=90),
    admin_auth: dict[str, Any] = Depends(require_admin_auth),
) -> SponsorshipAnalyticsResponse:
    try:
        data = await sponsorship_service.get_analytics(
            sponsor_id=sponsor_id.lower().strip(),
            daily_limit=daily_limit,
        )
        return SponsorshipAnalyticsResponse(
            sponsor_id=data.get("sponsor_id", sponsor_id),
            summary=data.get("summary", {}),
            daily=data.get("daily", []),
        )
    except Exception as e:
        logger.error("Failed to retrieve sponsorship analytics: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve sponsorship analytics.",
        ) from e

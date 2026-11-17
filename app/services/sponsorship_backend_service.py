"""
Server-side Sponsorship Service for SiratSync.

Executes privileged Firestore operations via Firebase Admin SDK,
enforces duplicate-click debouncing (Redis/in-memory), applies rate limiting,
and performs atomic analytics aggregation without requiring Firebase Cloud Functions or Blaze billing.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from firebase_admin import firestore
from app.core.security import get_firestore_client
from app.services.memory_service import memory

logger = logging.getLogger(__name__)

# Fallback in-memory structures if Redis is unavailable
_memory_debounce: dict[str, float] = {}
_memory_rate_limit: dict[str, list[float]] = {}
_memory_lock = threading.Lock()

DEBOUNCE_WINDOW_SECONDS = 1.5
MAX_CLICKS_PER_MINUTE = 20


class SponsorshipBackendService:
    """Handles server-side validation, rate limiting, and atomic analytics in Firestore."""

    # ── Duplicate Detection & Rate Limiting ──────────────────────────────
    async def is_duplicate_or_rate_limited(self, device_id: str, placement: str) -> tuple[bool, str]:
        """
        Checks whether the incoming click is a duplicate (rapid double tap <1.5s)
        or exceeds the rate limit (20 clicks/min).

        Returns: (is_blocked: bool, reason: str)
        """
        now = time.time()
        debounce_key = f"sponsorship:debounce:{device_id}:{placement}"
        rate_key = f"sponsorship:rate:{device_id}"

        # 1. Try Redis
        if memory.redis is not None:
            try:
                # Debounce check: set with 1500ms TTL, set only if not exists (NX)
                is_first = await memory.redis.set(debounce_key, "1", px=int(DEBOUNCE_WINDOW_SECONDS * 1000), nx=True)
                if not is_first:
                    return True, "debounced"

                # Rate limit check: sliding window / counter
                count = await memory.redis.incr(rate_key)
                if count == 1:
                    await memory.redis.expire(rate_key, 60)
                if count > MAX_CLICKS_PER_MINUTE:
                    return True, "rate_limited"

                return False, ""
            except Exception as e:
                logger.warning("Redis check failed for sponsorship click, using in-memory fallback: %s", e)

        # 2. In-memory fallback
        with _memory_lock:
            # Clean expired debounce entries
            expired_keys = [k for k, v in _memory_debounce.items() if now - v > 10.0]
            for k in expired_keys:
                _memory_debounce.pop(k, None)

            # Debounce
            mem_key = f"{device_id}:{placement}"
            last_time = _memory_debounce.get(mem_key, 0.0)
            if now - last_time < DEBOUNCE_WINDOW_SECONDS:
                return True, "debounced"
            _memory_debounce[mem_key] = now

            # Rate limit
            history = _memory_rate_limit.setdefault(device_id, [])
            history = [t for t in history if now - t < 60.0]
            _memory_rate_limit[device_id] = history
            if len(history) >= MAX_CLICKS_PER_MINUTE:
                return True, "rate_limited"
            history.append(now)

            return False, ""

    # ── Atomic Click Recording ───────────────────────────────────────────
    def _record_click_sync(
        self,
        placement: str,
        sponsor_id: str,
        device_id: str,
        client_timestamp: str | None,
        platform: str | None,
        user_id: str | None,
    ) -> dict[str, Any]:
        """Synchronous privileged Firestore atomic write operation."""
        db = get_firestore_client()
        if db is None:
            raise RuntimeError("Firestore client is unavailable.")

        click_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        is_home = placement == "home_banner"
        is_hadith = placement == "hadith_attribution"
        is_verse = placement == "verse_attribution"
        is_ibadah = is_hadith or is_verse

        batch = db.batch()

        # 1. Audit log in sponsorship_clicks/{click_id}
        click_ref = db.collection("sponsorship_clicks").document(click_id)
        batch.set(
            click_ref,
            {
                "click_id": click_id,
                "sponsor_id": sponsor_id,
                "placement": placement,
                "device_id": device_id,
                "user_id": user_id,
                "is_authenticated": user_id is not None,
                "date": date_str,
                "client_timestamp": client_timestamp or now.isoformat(),
                "timestamp": firestore.SERVER_TIMESTAMP,
                "platform": platform or "unknown",
            },
        )

        # 2. Main aggregated summary in sponsorship_analytics/{sponsor_id}
        summary_ref = db.collection("sponsorship_analytics").document(sponsor_id)
        batch.set(
            summary_ref,
            {
                "sponsor_id": sponsor_id,
                "total_clicks": firestore.Increment(1),
                "home_banner_clicks": firestore.Increment(1 if is_home else 0),
                "hadith_attribution_clicks": firestore.Increment(1 if is_hadith else 0),
                "verse_attribution_clicks": firestore.Increment(1 if is_verse else 0),
                "ibadah_attribution_clicks": firestore.Increment(1 if is_ibadah else 0),
                "last_click_at": firestore.SERVER_TIMESTAMP,
                "last_placement": placement,
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )

        # 3. Daily breakdown in sponsorship_analytics/{sponsor_id}/daily/{date_str}
        daily_ref = summary_ref.collection("daily").document(date_str)
        batch.set(
            daily_ref,
            {
                "date": date_str,
                "total_clicks": firestore.Increment(1),
                "home_banner": firestore.Increment(1 if is_home else 0),
                "hadith_attribution": firestore.Increment(1 if is_hadith else 0),
                "verse_attribution": firestore.Increment(1 if is_verse else 0),
                "ibadah_attribution": firestore.Increment(1 if is_ibadah else 0),
                "last_click_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )

        # 4. Anonymous unique device log in sponsorship_analytics/{sponsor_id}/unique_devices/{device_id}
        device_ref = summary_ref.collection("unique_devices").document(device_id)
        batch.set(
            device_ref,
            {
                "device_id": device_id,
                "total_clicks": firestore.Increment(1),
                "last_date": date_str,
                "last_placement": placement,
                "last_click_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )

        batch.commit()

        logger.info(
            "📊 [SponsorshipBackend] Recorded click %s on placement '%s' for '%s' (device: %s...)",
            click_id,
            placement,
            sponsor_id,
            device_id[:8],
        )

        return {
            "status": "recorded",
            "recorded": True,
            "click_id": click_id,
            "placement": placement,
            "message": "Click recorded successfully",
        }

    async def record_click(
        self,
        placement: str,
        sponsor_id: str,
        device_id: str,
        client_timestamp: str | None = None,
        platform: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Asynchronously records click in Firestore without blocking the event loop."""
        return await asyncio.to_thread(
            self._record_click_sync,
            placement,
            sponsor_id,
            device_id,
            client_timestamp,
            platform,
            user_id,
        )

    # ── Analytics Retrieval ──────────────────────────────────────────────
    def _get_analytics_sync(self, sponsor_id: str, daily_limit: int = 30) -> dict[str, Any]:
        db = get_firestore_client()
        if db is None:
            raise RuntimeError("Firestore client is unavailable.")

        summary_ref = db.collection("sponsorship_analytics").document(sponsor_id)
        summary_doc = summary_ref.get()
        summary_data = summary_doc.to_dict() if summary_doc.exists else {}

        # Convert timestamps in summary
        for k, v in list(summary_data.items()):
            if hasattr(v, "isoformat"):
                summary_data[k] = v.isoformat()

        daily_query = (
            summary_ref.collection("daily")
            .order_by("date", direction=firestore.Query.DESCENDING)
            .limit(daily_limit)
            .stream()
        )

        daily_list = []
        for d in daily_query:
            item = d.to_dict()
            for k, v in list(item.items()):
                if hasattr(v, "isoformat"):
                    item[k] = v.isoformat()
            daily_list.append(item)

        return {
            "sponsor_id": sponsor_id,
            "summary": summary_data,
            "daily": daily_list,
        }

    async def get_analytics(self, sponsor_id: str = "mathobah", daily_limit: int = 30) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_analytics_sync, sponsor_id, daily_limit)

    # ── Remote Configuration Management ──────────────────────────────────
    def _get_config_sync(self) -> dict[str, Any]:
        db = get_firestore_client()
        if db is None:
            raise RuntimeError("Firestore client is unavailable.")

        doc = db.collection("app_config").document("sponsorship").get()
        if not doc.exists:
            return {
                "is_active": False,
                "sponsor_name": "Mathobah",
                "tagline": "",
                "banner_url": "assets/images/ad_mathuba_light.jpeg",
                "banner_url_dark": "assets/images/ad_mathuba_dark.jpeg",
                "target_url": "https://mathoba.com/app/",
                "promo_code": "SIRATSYNC",
                "updated_at": None,
            }

        data = doc.to_dict() or {}
        updated_at = data.get("updated_at")
        if hasattr(updated_at, "isoformat"):
            data["updated_at"] = updated_at.isoformat()
        return data

    async def get_config(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_config_sync)

    def _update_config_sync(self, update_fields: dict[str, Any], updated_by: str | None = None) -> dict[str, Any]:
        db = get_firestore_client()
        if db is None:
            raise RuntimeError("Firestore client is unavailable.")

        clean_update = {k: v for k, v in update_fields.items() if v is not None}
        clean_update["updated_at"] = firestore.SERVER_TIMESTAMP
        if updated_by:
            clean_update["updated_by"] = updated_by

        doc_ref = db.collection("app_config").document("sponsorship")
        doc_ref.set(clean_update, merge=True)

        logger.info("✅ [SponsorshipBackend] Remote sponsorship config updated by %s", updated_by)
        return self._get_config_sync()

    async def update_config(self, update_fields: dict[str, Any], updated_by: str | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._update_config_sync, update_fields, updated_by)


sponsorship_service = SponsorshipBackendService()

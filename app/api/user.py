"""
Per-user profile/session endpoints.

Both routes expose personal data (message counts, consistency stats,
session deletion) and are protected by an internal API key — without this,
any caller who knows or guesses a `user_id` could read or wipe another
user's data. See app.core.security.require_internal_api_key.
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import require_internal_api_key
from app.services.memory_service import memory

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_internal_api_key)])


@router.get("/user/{user_id}/summary")
async def get_user_summary(user_id: str):
    if not user_id or not user_id.strip():
        raise HTTPException(status_code=400, detail="user_id cannot be empty")

    try:
        return {
            "user_id": user_id,
            "profile": memory.get_user_profile(user_id),
            "session": memory.get_session_summary(user_id),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error("Failed to fetch summary for user %s: %s", user_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve user summary") from e


@router.delete("/user/{user_id}/session")
async def clear_user_session(user_id: str):
    if not user_id or not user_id.strip():
        raise HTTPException(status_code=400, detail="user_id cannot be empty")

    try:
        memory.clear_session(user_id)
        return {"status": "success", "message": f"Session cleared for user {user_id}"}
    except Exception as e:
        logger.error("Failed to clear session for user %s: %s", user_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to clear user session") from e

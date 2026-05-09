from fastapi import APIRouter, HTTPException
from datetime import datetime
from app.services.memory_service import memory

router = APIRouter()

@router.get("/user/{user_id}/summary")
async def get_user_summary(user_id: str):
    try:
        return {
            "user_id":   user_id,
            "profile":   memory.get_user_profile(user_id),
            "session":   memory.get_session_summary(user_id),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/user/{user_id}/session")
async def clear_user_session(user_id: str):
    try:
        memory.clear_session(user_id)
        return {"status": "success", "message": f"Session cleared for user {user_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
from datetime import datetime, timedelta
from collections import defaultdict
from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.config import RATE_LIMIT_MAX_KEYS, RATE_LIMIT_RPM
import logging

logger = logging.getLogger(__name__)

rate_limits: dict = defaultdict(list)

async def rate_limit_middleware(request: Request, call_next):
    user_id = request.headers.get("X-User-ID", request.client.host)
    now = datetime.now()

    if len(rate_limits) > RATE_LIMIT_MAX_KEYS:
        rate_limits.clear()
        logger.warning("⚠️ rate_limits dict cleared (exceeded max keys)")

    rate_limits[user_id] = [
        t for t in rate_limits[user_id] if now - t < timedelta(minutes=1)
    ]

    if len(rate_limits[user_id]) >= RATE_LIMIT_RPM:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please wait a minute."}
        )

    rate_limits[user_id].append(now)
    return await call_next(request)
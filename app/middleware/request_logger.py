from datetime import datetime
from fastapi import Request
import logging

logger = logging.getLogger(__name__)

async def log_requests_middleware(request: Request, call_next):
    start = datetime.now()
    response = await call_next(request)
    duration = (datetime.now() - start).total_seconds()
    logger.info(f"{request.method} {request.url.path} → {response.status_code} ({duration:.2f}s)")
    return response
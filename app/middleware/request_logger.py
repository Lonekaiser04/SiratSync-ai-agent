"""
Request logging middleware with per-request correlation IDs, so a single
request's log lines (across middleware, services, and error handlers) can
be tied together — the previous version logged method/path/status/duration
only, with no way to correlate lines for concurrent requests.
"""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


async def log_requests_middleware(request: Request, call_next):
    request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
    request.state.request_id = request_id

    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.monotonic() - start) * 1000
        logger.exception(
            "request_id=%s method=%s path=%s status=UNHANDLED_ERROR duration_ms=%.1f",
            request_id, request.method, request.url.path, duration_ms,
        )
        raise

    duration_ms = (time.monotonic() - start) * 1000
    response.headers[REQUEST_ID_HEADER] = request_id

    log_level = logging.WARNING if response.status_code >= 400 else logging.INFO
    logger.log(
        log_level,
        "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
        request_id, request.method, request.url.path, response.status_code, duration_ms,
    )
    return response

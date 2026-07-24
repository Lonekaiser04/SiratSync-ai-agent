"""
Background keep-alive pinger for free-tier hosts (e.g. Render) that spin
down on inactivity. Started from the app's lifespan handler when
KEEP_ALIVE_ENABLED is set (RENDER=1 or KEEP_ALIVE=1 in the environment).
"""
import logging
import threading
import time

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

_PING_INTERVAL_SECONDS = 600  # 10 minutes
_PING_TIMEOUT_SECONDS = 5


def keep_render_alive() -> None:
    """Ping the health endpoint periodically to prevent spin-down."""
    url = settings.RENDER_URL

    def ping() -> None:
        while True:
            try:
                response = requests.get(url, timeout=_PING_TIMEOUT_SECONDS)
                logger.info("Keep-alive ping: %s", response.status_code)
            except requests.RequestException as e:
                logger.warning("Keep-alive ping failed: %s", e)
            time.sleep(_PING_INTERVAL_SECONDS)

    thread = threading.Thread(target=ping, daemon=True, name="keep-alive-pinger")
    thread.start()
    logger.info("Keep-alive service started (pings every %ds)", _PING_INTERVAL_SECONDS)

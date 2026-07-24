"""
Maintenance script: removes Redis data for users inactive beyond a
threshold. Intended to run on a schedule (e.g. daily cron / Render cron
job) since the app itself does not run this automatically.

Usage:
    python -m scripts.cleanup_memory [--inactive-days N] [--dry-run]
"""
import argparse
import logging
import sys

from app.services import memory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def cleanup_inactive_users(inactive_days: int = 60) -> int:
    """Run periodically to clean up inactive users. Returns the number
    of users cleaned up."""
    if not memory._is_redis_available():
        logger.warning("Redis is not available — nothing to clean up (in-memory fallback is ephemeral).")
        return 0

    cleaned = memory.cleanup_inactive_users(inactive_days=inactive_days)
    logger.info("Cleanup complete: %d inactive user(s) removed.", cleaned)
    return cleaned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inactive-days",
        type=int,
        default=60,
        help="Remove users inactive for at least this many days (default: 60)",
    )
    args = parser.parse_args()

    try:
        cleanup_inactive_users(inactive_days=args.inactive_days)
        return 0
    except Exception:
        logger.exception("Cleanup job failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())

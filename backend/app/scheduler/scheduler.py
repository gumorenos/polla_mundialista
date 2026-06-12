"""APScheduler configuration and entry point.

Periodic jobs (full data refresh, news scan) are registered here.
Populated in Prompt 10.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


def start_scheduler() -> None:
    logger.info("Scheduler started — no periodic jobs configured yet")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    from app.core.logging import setup_logging

    setup_logging()
    start_scheduler()

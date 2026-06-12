"""Background task definitions for RQ workers.

Each public function here is safe to enqueue via rq.Queue.enqueue().
Heavy tasks (Monte Carlo, ML training) will be added in later prompts.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def ping_task() -> str:
    """Sanity-check task: logs execution and returns 'pong'."""
    logger.info("ping_task executed")
    return "pong"

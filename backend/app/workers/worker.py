"""RQ worker entry point.

Listens on queues: default, long, ml, news.
Run directly:  python -m app.workers.worker
Or via rq CLI: rq worker --url $REDIS_URL default long ml news
"""

from __future__ import annotations

import sys

from redis import Redis
from rq import Queue, Worker

from app.core.config import settings
from app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)

QUEUE_NAMES = ["default", "long", "ml", "news"]


def start_worker() -> None:
    setup_logging()
    logger.info("Starting RQ worker — queues: %s", QUEUE_NAMES)
    redis_conn = Redis.from_url(settings.REDIS_URL)
    queues = [Queue(name, connection=redis_conn) for name in QUEUE_NAMES]
    worker = Worker(queues, connection=redis_conn)
    worker.work()


if __name__ == "__main__":
    start_worker()

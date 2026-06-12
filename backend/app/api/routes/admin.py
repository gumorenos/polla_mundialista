from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, status
from redis import Redis
from rq import Queue

from app.core.config import settings
from app.workers.tasks import run_ingestion_pipeline, run_news_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(x_admin_token: str | None) -> None:
    """Raise 403 if ADMIN_TOKEN is set and the header doesn't match."""
    if not settings.ADMIN_TOKEN:
        logger.warning("ADMIN_TOKEN is empty — /admin endpoints are unprotected")
        return
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-Admin-Token",
        )


@router.post("/ingest")
def enqueue_ingest(x_admin_token: str | None = Header(default=None)):
    """Enqueue the full ingestion pipeline in the default RQ queue."""
    _require_admin(x_admin_token)
    redis_conn = Redis.from_url(settings.REDIS_URL)
    q = Queue("default", connection=redis_conn)
    job = q.enqueue(run_ingestion_pipeline, job_timeout=settings.RQ_LONG_TIMEOUT)
    logger.info("Ingestion job enqueued: %s", job.id)
    return {"job_id": job.id, "status": "enqueued", "queue": "default"}


@router.post("/refresh-news")
def enqueue_refresh_news(x_admin_token: str | None = Header(default=None)):
    """Enqueue injury/news analysis in the 'news' RQ queue."""
    from app.db.connection import db_transaction
    from app.db.repositories.jobs import JobRepository

    _require_admin(x_admin_token)

    with db_transaction() as conn:
        job_repo = JobRepository(conn)
        job_id   = job_repo.create({"job_type": "news", "status": "enqueued"})
        conn.commit()

    redis_conn = Redis.from_url(settings.REDIS_URL)
    q   = Queue("news", connection=redis_conn)
    job = q.enqueue(run_news_task, job_id, job_timeout=settings.RQ_DEFAULT_TIMEOUT)
    logger.info("News refresh job enqueued: rq_job=%s db_job=%s", job.id, job_id)
    return {"job_id": job_id, "rq_job_id": job.id, "status": "enqueued", "queue": "news"}

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from redis import Redis
from rq import Queue

from app.api.dependencies import require_admin
from app.core.config import settings
from app.core.limiter import limiter
from app.workers.tasks import run_ingestion_pipeline, run_news_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/ingest", dependencies=[Depends(require_admin)])
@limiter.limit(settings.RATE_LIMIT_ADMIN)
def enqueue_ingest(request: Request):
    """Enqueue the full ingestion pipeline in the default RQ queue."""
    from app.db.connection import db_transaction
    from app.db.repositories.jobs import JobRepository

    with db_transaction() as conn:
        job_id = JobRepository(conn).create({
            "job_type": "ingestion",
            "status": "enqueued",
            "progress": 0.0,
        })
        conn.commit()

    redis_conn = Redis.from_url(settings.REDIS_URL)
    q = Queue("default", connection=redis_conn)
    job = q.enqueue(run_ingestion_pipeline, job_id, job_timeout=settings.RQ_LONG_TIMEOUT)
    try:
        with db_transaction() as conn:
            JobRepository(conn).update_rq_job_id(job_id, job.id)
            conn.commit()
    except Exception:
        logger.exception("Ingestion job enqueued in RQ but rq_job_id update failed: db_job=%s rq=%s", job_id, job.id)
    logger.info("Ingestion job enqueued: rq_job=%s db_job=%s", job.id, job_id)
    return {"job_id": job_id, "rq_job_id": job.id, "status": "enqueued", "queue": "default"}


@router.post("/refresh-news", dependencies=[Depends(require_admin)])
@limiter.limit(settings.RATE_LIMIT_ADMIN)
def enqueue_refresh_news(request: Request):
    """Enqueue injury/news analysis in the 'news' RQ queue."""
    from app.db.connection import db_transaction
    from app.db.repositories.jobs import JobRepository

    with db_transaction() as conn:
        job_repo = JobRepository(conn)
        job_id = job_repo.create({"job_type": "news", "status": "enqueued"})
        conn.commit()

    redis_conn = Redis.from_url(settings.REDIS_URL)
    q = Queue("news", connection=redis_conn)
    job = q.enqueue(run_news_task, job_id, job_timeout=settings.RQ_DEFAULT_TIMEOUT)
    try:
        with db_transaction() as conn:
            JobRepository(conn).update_rq_job_id(job_id, job.id)
            conn.commit()
    except Exception:
        logger.exception("News refresh enqueued in RQ but rq_job_id update failed: db_job=%s rq=%s", job_id, job.id)
    logger.info("News refresh job enqueued: rq_job=%s db_job=%s", job.id, job_id)
    return {"job_id": job_id, "rq_job_id": job.id, "status": "enqueued", "queue": "news"}

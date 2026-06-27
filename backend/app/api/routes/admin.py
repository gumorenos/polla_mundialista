from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from redis import Redis
from rq import Queue

from app.api.dependencies import require_admin
from app.core.config import settings
from app.core.limiter import limiter
from app.workers.tasks import run_ingestion_pipeline, run_news_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


class ResetBody(BaseModel):
    confirm: bool = False


@router.post("/reset", dependencies=[Depends(require_admin)])
@limiter.limit(settings.RATE_LIMIT_ADMIN)
def admin_reset(request: Request, body: ResetBody) -> dict[str, Any]:
    """Full database and cache reset.

    Truncates transient tables (simulations, predictions, news, jobs,
    evaluations) while preserving StatsBomb historical data and reference tables.
    Requires { "confirm": true } in the request body as a second-confirmation guard.
    """
    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true to proceed")

    from app.db.connection import db_transaction

    from app.db.repositories.admin import AdminRepository

    with db_transaction() as conn:
        repo = AdminRepository(conn)
        deleted = repo.reset_transient_data()
        repo.vacuum()

    # Flush Redis caches (fault-tolerant — reset still succeeds if Redis unavailable)
    redis_status = "ok"
    try:
        redis_conn = Redis.from_url(settings.REDIS_URL)
        redis_conn.flushdb()
    except Exception as exc:
        logger.warning("admin_reset: Redis flush failed: %s", exc)
        redis_status = f"failed: {exc}"

    logger.info("admin_reset completed: %s | redis=%s", deleted, redis_status)
    return {
        "status":    "reset_complete",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "deleted":   deleted,
        "redis":     redis_status,
    }


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

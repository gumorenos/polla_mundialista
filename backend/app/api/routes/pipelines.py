"""Pipeline endpoints — enqueue full refresh, daily update, and all-models simulation."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from redis import Redis
from rq import Queue

from app.core.config import settings
from app.db.connection import db_transaction
from app.db.repositories.jobs import JobRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])

_BASE_MODELS = ["baseline", "elo", "poisson", "poisson_context"]
_ALL_MODELS  = _BASE_MODELS + ["ml_calibrated"]


def _require_admin(x_admin_token: str | None) -> None:
    if not settings.ADMIN_TOKEN:
        return
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-Admin-Token",
        )


# ---------------------------------------------------------------------------
# POST /api/pipelines/full-refresh
# ---------------------------------------------------------------------------

@router.post("/full-refresh")
def enqueue_full_refresh(
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Enqueue the full data refresh pipeline in the 'long' RQ queue."""
    from app.workers.tasks import run_full_refresh_task

    _require_admin(x_admin_token)

    with db_transaction() as conn:
        job_id = JobRepository(conn).create({
            "job_type": "full_refresh",
            "status":   "enqueued",
            "progress": 0.0,
        })
        conn.commit()

    redis_conn = Redis.from_url(settings.REDIS_URL)
    q = Queue("long", connection=redis_conn)
    rq_job = q.enqueue(
        run_full_refresh_task, job_id,
        job_timeout=settings.RQ_LONG_TIMEOUT,
    )

    with db_transaction() as conn:
        JobRepository(conn).update_status(job_id, "enqueued", result_ref=rq_job.id)
        conn.commit()

    logger.info("Full refresh enqueued: rq=%s db_job=%s", rq_job.id, job_id)
    return {"job_id": job_id, "rq_job_id": rq_job.id, "status": "enqueued"}


# ---------------------------------------------------------------------------
# POST /api/pipelines/daily-update
# ---------------------------------------------------------------------------

@router.post("/daily-update")
def enqueue_daily_update(
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Enqueue the incremental daily update in the 'default' RQ queue."""
    from app.workers.tasks import run_daily_update_task

    _require_admin(x_admin_token)

    with db_transaction() as conn:
        job_id = JobRepository(conn).create({
            "job_type": "daily_update",
            "status":   "enqueued",
            "progress": 0.0,
        })
        conn.commit()

    redis_conn = Redis.from_url(settings.REDIS_URL)
    q = Queue("default", connection=redis_conn)
    rq_job = q.enqueue(
        run_daily_update_task, job_id,
        job_timeout=settings.RQ_DEFAULT_TIMEOUT,
    )

    with db_transaction() as conn:
        JobRepository(conn).update_status(job_id, "enqueued", result_ref=rq_job.id)
        conn.commit()

    logger.info("Daily update enqueued: rq=%s db_job=%s", rq_job.id, job_id)
    return {"job_id": job_id, "rq_job_id": rq_job.id, "status": "enqueued"}


# ---------------------------------------------------------------------------
# POST /api/pipelines/run-all-models
# ---------------------------------------------------------------------------

@router.post("/run-all-models")
def enqueue_all_models(
    x_admin_token: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    """Enqueue one Monte Carlo simulation per model.  Returns a list of job records."""
    from app.workers.tasks import run_simulation_task

    _require_admin(x_admin_token)

    redis_conn = Redis.from_url(settings.REDIS_URL)
    q = Queue("long", connection=redis_conn)

    jobs: list[dict[str, Any]] = []

    with db_transaction() as conn:
        job_repo = JobRepository(conn)
        for model_name in _ALL_MODELS:
            job_id = job_repo.create({
                "job_type": "simulation",
                "status":   "enqueued",
                "progress": 0.0,
            })
        conn.commit()

    # Re-open so we can enqueue and update result_ref
    for model_name in _ALL_MODELS:
        with db_transaction() as conn:
            job_id = JobRepository(conn).create({
                "job_type": "simulation",
                "status":   "enqueued",
                "progress": 0.0,
            })
            conn.commit()

        rq_job = q.enqueue(
            run_simulation_task,
            model_name,
            settings.MONTECARLO_ITERATIONS,
            settings.MONTECARLO_SEED,
            job_id,
            job_timeout=settings.RQ_LONG_TIMEOUT,
        )

        with db_transaction() as conn:
            JobRepository(conn).update_status(job_id, "enqueued", result_ref=rq_job.id)
            conn.commit()

        jobs.append({
            "job_id":     job_id,
            "rq_job_id":  rq_job.id,
            "model_name": model_name,
            "status":     "enqueued",
        })

    logger.info("run-all-models: %d simulations enqueued", len(jobs))
    return jobs

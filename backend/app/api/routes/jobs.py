"""Jobs endpoints — list, inspect, and cancel background job records."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

import redis as redis_lib
from rq import cancel_job as rq_cancel_job
from rq.job import Job as RQJob

from app.api.dependencies import require_admin
from app.core.config import settings
from app.core.limiter import limiter
from app.db.connection import db_transaction
from app.db.repositories.jobs import JobRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def list_jobs(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    """Return the most recent job records."""
    with db_transaction() as conn:
        return JobRepository(conn).list_recent(limit)


@router.get("/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    """Return a single job record by ID."""
    with db_transaction() as conn:
        job = JobRepository(conn).get_by_id(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )
    return job


@router.delete("/{job_id}", dependencies=[Depends(require_admin)])
@limiter.limit(settings.RATE_LIMIT_ADMIN)
def cancel_job(request: Request, job_id: str) -> dict[str, Any]:
    """Cancel an enqueued or running job."""
    with db_transaction() as conn:
        job = JobRepository(conn).get_by_id(job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job '{job_id}' not found",
            )
        if job["status"] not in ("enqueued", "started", "running"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Job is '{job['status']}' and cannot be cancelled",
            )

        # Attempt to cancel in RQ if we have an rq_job_id
        rq_job_id = job.get("rq_job_id")
        if rq_job_id:
            try:
                redis_conn = redis_lib.from_url(settings.REDIS_URL)
                rq_job = RQJob.fetch(rq_job_id, connection=redis_conn)
                rq_job.cancel()
                logger.info("RQ job %s cancelled", rq_job_id)
            except Exception as exc:  # noqa: BLE001
                # Non-fatal: job may have already finished or RQ is unavailable
                logger.warning("Could not cancel RQ job %s: %s", rq_job_id, exc)

        cancelled = JobRepository(conn).cancel(job_id)

    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job could not be cancelled (already finished?)",
        )

    logger.info("Job %s cancelled by admin", job_id)
    return {"cancelled": True, "job_id": job_id}

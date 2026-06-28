"""Jobs endpoints — list, inspect, and cancel background job records."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request, status

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

_SENSITIVE_FIELDS = {"error_message", "result_ref", "rq_job_id"}


def _check_admin(x_admin_token: str, admin_session: str) -> bool:
    """Return True if the request carries valid admin credentials (no exception)."""
    if not settings.ADMIN_TOKEN:
        return False
    import secrets as _sec
    if x_admin_token and _sec.compare_digest(x_admin_token, settings.ADMIN_TOKEN):
        return True
    if admin_session:
        from app.api.routes.auth import is_session_valid
        if is_session_valid(admin_session):
            return True
    return False


def _sanitize(job: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in job.items() if k not in _SENSITIVE_FIELDS}


@router.get("")
def list_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    x_admin_token: str = Header(default=""),
    admin_session: str = Cookie(default=""),
) -> list[dict[str, Any]]:
    """Return recent job records. Admin callers receive full details; public callers get sanitized data."""
    is_admin = _check_admin(x_admin_token, admin_session)
    with db_transaction() as conn:
        jobs = JobRepository(conn).list_recent(limit)
    return jobs if is_admin else [_sanitize(j) for j in jobs]


@router.get("/{job_id}")
def get_job(
    job_id: str,
    x_admin_token: str = Header(default=""),
    admin_session: str = Cookie(default=""),
) -> dict[str, Any]:
    """Return a single job. Admin callers receive full details; public callers get sanitized data."""
    is_admin = _check_admin(x_admin_token, admin_session)
    with db_transaction() as conn:
        job = JobRepository(conn).get_by_id(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )
    return job if is_admin else _sanitize(job)


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

        rq_job_id = job.get("rq_job_id")
        job_status = job["status"]

        if job_status == "enqueued":
            # Job is queued but not yet running: cancel in RQ immediately
            if rq_job_id:
                try:
                    redis_conn = redis_lib.from_url(settings.REDIS_URL)
                    rq_job = RQJob.fetch(rq_job_id, connection=redis_conn)
                    rq_job.cancel()
                    logger.info("RQ job %s cancelled (enqueued)", rq_job_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not cancel RQ job %s: %s", rq_job_id, exc)
            cancelled = JobRepository(conn).cancel(job_id)
        else:
            # Job is running: request graceful stop via 'cancelling' status.
            # The worker's heartbeat detects this and stops the task cleanly,
            # keeping the worker process alive to process subsequent jobs.
            # We do NOT call rq_job.cancel() here to avoid killing the worker.
            requested = JobRepository(conn).request_cancel(job_id)
            cancelled = requested  # from the caller's perspective, cancellation was requested

    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job could not be cancelled (already finished?)",
        )

    logger.info("Job %s cancel requested (was: %s) by admin", job_id, job.get("status"))
    return {"cancelled": True, "job_id": job_id}


@router.post("/{job_id}/force-cancel", dependencies=[Depends(require_admin)])
@limiter.limit(settings.RATE_LIMIT_ADMIN)
def force_cancel_job(request: Request, job_id: str) -> dict[str, Any]:
    """Force a job to cancelled regardless of its current state.

    Use when cancel leaves a job stuck in 'cancelling'. Does NOT attempt
    graceful shutdown — updates DB directly and cancels in RQ if possible.
    """
    with db_transaction() as conn:
        job = JobRepository(conn).get_by_id(job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job '{job_id}' not found",
            )
        if job["status"] in ("completed", "failed", "cancelled"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Job is already in terminal state '{job['status']}'",
            )

        # Best-effort RQ cancellation (don't fail if Redis unreachable)
        rq_job_id = job.get("rq_job_id")
        if rq_job_id:
            try:
                redis_conn = redis_lib.from_url(settings.REDIS_URL)
                rq_job = RQJob.fetch(rq_job_id, connection=redis_conn)
                rq_job.cancel()
                logger.info("force-cancel: RQ job %s cancelled", rq_job_id)
            except Exception as exc:
                logger.warning("force-cancel: could not cancel RQ job %s: %s", rq_job_id, exc)

        # Force DB to cancelled regardless
        JobRepository(conn).force_cancel(job_id)

    logger.info("Job %s force-cancelled by admin (was: %s)", job_id, job.get("status"))
    return {"force_cancelled": True, "job_id": job_id, "previous_status": job["status"]}

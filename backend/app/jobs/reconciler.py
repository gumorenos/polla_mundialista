"""Reconcile abandoned RQ jobs with DB job records.

Runs at startup and periodically from the scheduler.
Never runs inside GET endpoints (no writes from read paths).

Logic:
- For active DB jobs (enqueued/started/running/cancelling) with an rq_job_id:
    - Fetch from RQ; if RQ says failed/stopped/cancelled → update DB.
    - If Redis is unreachable: skip (no false failures).
    - If job not found in RQ (NoSuchJobError): treat as orphan.
- For orphan jobs (no rq_job_id or not in Redis):
    - Only mark failed if no recent heartbeat AND older than 30 minutes.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import redis as redis_lib
from rq.job import Job as RQJob

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = ("enqueued", "started", "running", "cancelling")
_ORPHAN_MAX_AGE_MINUTES = 30
_HEARTBEAT_STALE_MINUTES = 10
_CANCELLING_TIMEOUT_MINUTES = 10  # force-cancel if stuck in cancelling > 10 min


def reconcile_rq_jobs(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    """Check active DB jobs against RQ and fix stale records.

    Pass *conn* to run against an in-memory connection (tests only).
    Otherwise opens its own short-lived connection.

    Returns:
        {"updated": int, "skipped": int, "errors": int}
    """
    updated = skipped = errors = 0

    def _run(c: sqlite3.Connection) -> None:
        nonlocal updated, skipped, errors
        from app.db.repositories.jobs import JobRepository

        repo = JobRepository(c)
        active_jobs = repo.list_active()

        for job in active_jobs:
            try:
                changed = _check_one_job(c, repo, job)
                if changed:
                    updated += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.warning(
                    "reconcile: error checking job %s: %s", job["id"], exc
                )
                errors += 1

    if conn is not None:
        _run(conn)
    else:
        from app.db.connection import db_transaction
        with db_transaction() as c:
            _run(c)

    if updated > 0:
        logger.info(
            "reconcile_rq_jobs: updated=%d skipped=%d errors=%d",
            updated, skipped, errors,
        )
    return {"updated": updated, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_one_job(
    conn: sqlite3.Connection,
    repo: Any,
    job: dict[str, Any],
) -> bool:
    """Return True if the DB record was updated."""
    rq_job_id = job.get("rq_job_id")
    if rq_job_id:
        return _check_rq_job(conn, repo, job, rq_job_id)
    return _check_orphan_job(conn, repo, job)


def _check_rq_job(
    conn: sqlite3.Connection,
    repo: Any,
    job: dict[str, Any],
    rq_job_id: str,
) -> bool:
    """Fetch job status from RQ and reconcile."""
    try:
        from app.core.config import settings

        redis_conn = redis_lib.from_url(settings.REDIS_URL, socket_timeout=3)
        rq_job = RQJob.fetch(rq_job_id, connection=redis_conn)
        rq_status_obj = rq_job.get_status()
        rq_status = (
            rq_status_obj.value
            if hasattr(rq_status_obj, "value")
            else str(rq_status_obj)
        )
    except Exception as exc:
        exc_name = type(exc).__name__
        if "NoSuchJobError" in exc_name or "does not exist" in str(exc).lower():
            # Not in Redis → treat as orphan
            return _check_orphan_job(conn, repo, job)
        # Redis unreachable or other transient error → skip, don't mark failed
        logger.debug(
            "reconcile: can't reach Redis for job %s (rq=%s): %s",
            job["id"], rq_job_id, exc,
        )
        return False

    db_status = job["status"]
    job_id = job["id"]
    now_iso = datetime.now(timezone.utc).isoformat()

    if rq_status in ("failed", "stopped") and db_status in _ACTIVE_STATUSES:
        repo.update_status(
            job_id, "failed",
            finished_at=now_iso,
            error_message=f"Worker died or timed out (RQ status: {rq_status})",
        )
        conn.commit()
        logger.info(
            "reconcile: job %s marked failed (RQ: %s, DB was: %s)",
            job_id, rq_status, db_status,
        )
        return True

    if rq_status == "cancelled" and db_status in _ACTIVE_STATUSES:
        repo.update_status(
            job_id, "cancelled",
            finished_at=now_iso,
            error_message="Cancelled (reconciled from RQ state)",
        )
        conn.commit()
        logger.info(
            "reconcile: job %s marked cancelled (RQ: %s, DB was: %s)",
            job_id, rq_status, db_status,
        )
        return True

    # Force-cancel jobs stuck in 'cancelling' beyond the timeout
    if db_status == "cancelling":
        if _force_cancel_if_timed_out(conn, repo, job, job_id, now_iso):
            return True

    return False


def _check_orphan_job(
    conn: sqlite3.Connection,
    repo: Any,
    job: dict[str, Any],
) -> bool:
    """Apply age-based rule for jobs not (or no longer) in RQ."""
    job_id = job["id"]
    now = datetime.now(timezone.utc)

    # If heartbeat is recent, worker is still alive
    heartbeat_str = job.get("last_heartbeat")
    if heartbeat_str:
        try:
            hb_dt = datetime.fromisoformat(heartbeat_str.replace("Z", "+00:00"))
            if hb_dt.tzinfo is None:
                hb_dt = hb_dt.replace(tzinfo=timezone.utc)
            if now - hb_dt < timedelta(minutes=_HEARTBEAT_STALE_MINUTES):
                return False
        except Exception:
            pass

    # Check age from created_at (always present) or started_at
    age_ref = job.get("started_at") or job.get("created_at")
    if not age_ref:
        return False
    try:
        age_dt = datetime.fromisoformat(age_ref.replace("Z", "+00:00"))
        if age_dt.tzinfo is None:
            age_dt = age_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return False

    if now - age_dt > timedelta(minutes=_ORPHAN_MAX_AGE_MINUTES):
        repo.update_status(
            job_id, "failed",
            finished_at=now.isoformat(),
            error_message="Job stuck: no rq_job_id, no recent heartbeat, older than 30 min",
        )
        conn.commit()
        logger.info(
            "reconcile: orphan job %s marked failed (age=%s)",
            job_id, now - age_dt,
        )
        return True

    # Force-cancel jobs stuck in 'cancelling' beyond the timeout
    now_iso = now.isoformat()
    if job.get("status") == "cancelling":
        if _force_cancel_if_timed_out(conn, repo, job, job_id, now_iso):
            return True

    return False


def _force_cancel_if_timed_out(
    conn: sqlite3.Connection,
    repo: Any,
    job: dict[str, Any],
    job_id: str,
    now_iso: str,
) -> bool:
    """Force-cancel a job if it has been stuck in 'cancelling' too long.

    Returns True if the record was updated.
    """
    cancelling_at_str = job.get("cancelling_requested_at")
    if not cancelling_at_str:
        return False
    try:
        now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        cancelling_dt = datetime.fromisoformat(
            cancelling_at_str.replace("Z", "+00:00")
        )
        if cancelling_dt.tzinfo is None:
            cancelling_dt = cancelling_dt.replace(tzinfo=timezone.utc)
        if now - cancelling_dt > timedelta(minutes=_CANCELLING_TIMEOUT_MINUTES):
            repo.update_status(
                job_id, "cancelled",
                finished_at=now_iso,
                error_message=(
                    f"Force-cancelled after {_CANCELLING_TIMEOUT_MINUTES} min "
                    "in cancelling state (worker did not acknowledge in time)"
                ),
            )
            conn.commit()
            logger.info(
                "reconcile: job %s force-cancelled after %s in cancelling state",
                job_id, now - cancelling_dt,
            )
            return True
    except Exception as exc:
        logger.debug(
            "reconcile: could not parse cancelling_requested_at for %s: %s",
            job_id, exc,
        )
    return False

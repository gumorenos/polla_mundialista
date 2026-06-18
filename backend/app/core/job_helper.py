"""Helper for creating DB job records and enqueueing in RQ.

Separates the pattern that was duplicated across route handlers:
  1. Create DB record (with retry on SQLite lock)
  2. Enqueue in RQ
  3. Save rq_job_id (best-effort)

If Redis fails after the DB record is created, the job is marked failed
immediately so it never gets stuck in 'enqueued' forever.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Callable

from redis import Redis
from rq import Queue

from app.db.connection import db_transaction
from app.db.repositories.jobs import JobRepository

logger = logging.getLogger(__name__)

_MAX_LOCK_RETRIES = 3
_LOCK_BACKOFF_BASE = 0.2  # seconds


def _is_lock_error(exc: sqlite3.OperationalError) -> bool:
    return "database is locked" in str(exc).lower()


def enqueue_job(
    queue_name: str,
    task_fn: Callable,
    *extra_task_args: Any,
    job_type: str,
    timeout: int,
) -> dict[str, Any]:
    """Create a DB job record and enqueue the task in RQ.

    Args:
        queue_name:       RQ queue name (e.g. 'default', 'long', 'news').
        task_fn:          RQ task callable. Receives (job_id, *extra_task_args).
        *extra_task_args: Additional positional args passed to task_fn after job_id.
        job_type:         Value stored in jobs.job_type.
        timeout:          RQ job_timeout in seconds.

    Returns:
        {"job_id": str, "rq_job_id": str, "status": "enqueued"}

    Raises:
        sqlite3.OperationalError: if DB create fails after all retries.
        Exception: re-raised if Redis enqueue fails (job is marked failed first).
    """
    from app.core.config import settings

    # ── Step 1: Create DB record with retry on SQLite lock ─────────────────
    job_id: str | None = None
    for attempt in range(1, _MAX_LOCK_RETRIES + 1):
        try:
            with db_transaction() as conn:
                job_id = JobRepository(conn).create({
                    "job_type": job_type,
                    "status":   "enqueued",
                    "progress": 0.0,
                })
            break  # success — out of retry loop
        except sqlite3.OperationalError as exc:
            if _is_lock_error(exc) and attempt < _MAX_LOCK_RETRIES:
                delay = _LOCK_BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "enqueue_job: DB locked creating '%s' job (attempt %d/%d), retry in %.1fs",
                    job_type, attempt, _MAX_LOCK_RETRIES, delay,
                )
                time.sleep(delay)
            else:
                raise

    # ── Step 2: Enqueue in RQ ───────────────────────────────────────────────
    try:
        redis_conn = Redis.from_url(settings.REDIS_URL)
        q = Queue(queue_name, connection=redis_conn)
        rq_job = q.enqueue(task_fn, job_id, *extra_task_args, job_timeout=timeout)
    except Exception as exc:
        logger.error(
            "enqueue_job: Redis failed after creating DB job %s (%s): %s — marking failed",
            job_id, job_type, exc,
        )
        try:
            with db_transaction() as conn:
                JobRepository(conn).update_status(
                    str(job_id), "failed",
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    error_message=f"Redis unavailable: {type(exc).__name__}",
                )
        except Exception:
            logger.exception(
                "enqueue_job: also failed to mark job %s as failed in DB", job_id
            )
        raise

    # ── Step 3: Save rq_job_id (best-effort) ───────────────────────────────
    try:
        with db_transaction() as conn:
            JobRepository(conn).update_rq_job_id(str(job_id), rq_job.id)
    except Exception:
        logger.exception(
            "enqueue_job: %s job enqueued in RQ but rq_job_id update failed: "
            "db_job=%s rq=%s",
            job_type, job_id, rq_job.id,
        )

    logger.info(
        "enqueue_job: %s enqueued — rq=%s db_job=%s", job_type, rq_job.id, job_id
    )
    return {"job_id": job_id, "rq_job_id": rq_job.id, "status": "enqueued"}

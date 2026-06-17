from __future__ import annotations

import sqlite3
import uuid
from typing import Any


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r else None


class JobRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def create(self, job: dict[str, Any]) -> str:
        job_id = job.get("id") or str(uuid.uuid4())
        self._c.execute(
            """
            INSERT OR IGNORE INTO jobs
                (id, rq_job_id, job_type, status, progress)
            VALUES (:id, :rq_job_id, :job_type, :status, :progress)
            """,
            {
                "id":        job_id,
                "rq_job_id": job.get("rq_job_id"),
                "job_type":  job.get("job_type"),
                "status":    job.get("status", "enqueued"),
                "progress":  job.get("progress", 0.0),
            },
        )
        return job_id

    def update_status(
        self,
        job_id: str,
        status: str,
        started_at: str | None = None,
        finished_at: str | None = None,
        error_message: str | None = None,
        result_ref: str | None = None,
        rq_job_id: str | None = None,
    ) -> None:
        self._c.execute(
            """
            UPDATE jobs
            SET status        = ?,
                started_at    = COALESCE(?, started_at),
                finished_at   = COALESCE(?, finished_at),
                error_message = COALESCE(?, error_message),
                result_ref    = COALESCE(?, result_ref),
                rq_job_id     = COALESCE(?, rq_job_id)
            WHERE id = ?
            """,
            (status, started_at, finished_at, error_message, result_ref, rq_job_id, job_id),
        )

    def update_progress(self, job_id: str, progress: float) -> None:
        self._c.execute(
            "UPDATE jobs SET progress = ? WHERE id = ?", (progress, job_id)
        )

    def update_heartbeat(self, job_id: str) -> None:
        """Stamp last_heartbeat with the current UTC time."""
        self._c.execute(
            "UPDATE jobs SET last_heartbeat = datetime('now') WHERE id = ?",
            (job_id,),
        )

    def get_by_id(self, job_id: str) -> dict[str, Any] | None:
        return _row(
            self._c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        )

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self._c.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        ]

    def cancel(self, job_id: str) -> bool:
        """Mark job as cancelled immediately (for enqueued jobs). Returns True if updated."""
        cur = self._c.execute(
            """
            UPDATE jobs
            SET status = 'cancelled',
                finished_at = datetime('now'),
                error_message = 'Cancelled by admin'
            WHERE id = ? AND status IN ('enqueued', 'started', 'running')
            """,
            (job_id,),
        )
        return cur.rowcount > 0

    def request_cancel(self, job_id: str) -> bool:
        """Mark a running job as 'cancelling' for graceful shutdown by the worker.

        The worker's heartbeat thread detects 'cancelling' and signals the task
        to stop cleanly, keeping the worker process alive for subsequent jobs.
        Returns True if the status was updated.
        """
        cur = self._c.execute(
            """
            UPDATE jobs
            SET status = 'cancelling'
            WHERE id = ? AND status IN ('started', 'running')
            """,
            (job_id,),
        )
        return cur.rowcount > 0

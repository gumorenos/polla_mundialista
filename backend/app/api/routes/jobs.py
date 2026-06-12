"""Jobs endpoints — list and inspect background job records."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

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

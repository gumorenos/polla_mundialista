from __future__ import annotations

from fastapi import APIRouter
from redis import Redis
from rq import Queue

from app.core.config import settings
from app.workers.tasks import ping_task

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health_check():
    return {"status": "ok", "service": "oraculo-mundial-2026"}


@router.get("/api/jobs/ping")
def enqueue_ping():
    """Enqueue a ping_task job and return its ID."""
    redis_conn = Redis.from_url(settings.REDIS_URL)
    q = Queue("default", connection=redis_conn)
    job = q.enqueue(ping_task, job_timeout=settings.RQ_DEFAULT_TIMEOUT)
    return {"job_id": job.id, "status": "enqueued"}

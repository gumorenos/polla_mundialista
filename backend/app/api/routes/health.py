from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health_check():
    return {"status": "ok", "service": "oraculo-mundial-2026"}


@router.get("/api/jobs/ping")
def ping_redis():
    """Health check for Redis — does NOT enqueue jobs."""
    try:
        from redis import Redis
        conn = Redis.from_url(settings.REDIS_URL)
        conn.ping()
        return {"redis": "ok"}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Redis unavailable: {exc}",
        ) from exc

from __future__ import annotations

import hashlib
import logging
import secrets
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

_API_KEY_PREFIX_LEN = 12  # e.g. "om26_ab12cd3" — enough to tell keys apart, never the full key


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


# ---------------------------------------------------------------------------
# Public API key management — /api/admin/api-keys
# ---------------------------------------------------------------------------

class CreateApiKeyBody(BaseModel):
    label: str
    scopes: str = "read"
    rate_limit_per_minute: int = 60
    notes: str | None = None


@router.get("/api-keys", dependencies=[Depends(require_admin)])
@limiter.limit(settings.RATE_LIMIT_ADMIN)
def list_api_keys(request: Request) -> dict[str, Any]:
    """List public API keys — never returns the raw key or its hash."""
    from app.db.connection import db_transaction
    from app.db.repositories.api_keys import ApiKeyRepository

    with db_transaction() as conn:
        keys = ApiKeyRepository(conn).list_all()
    return {"keys": keys}


@router.post("/api-keys", dependencies=[Depends(require_admin)])
@limiter.limit(settings.RATE_LIMIT_ADMIN)
def create_api_key(request: Request, body: CreateApiKeyBody) -> dict[str, Any]:
    """Create a new public API key. The raw key is returned ONLY in this
    response — it is never stored or retrievable afterwards, only its hash."""
    from app.db.connection import db_transaction
    from app.db.repositories.api_keys import ApiKeyRepository

    raw_key = f"om26_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    prefix = raw_key[:_API_KEY_PREFIX_LEN]

    with db_transaction() as conn:
        key_id = ApiKeyRepository(conn).create_with_prefix(
            key_hash, prefix, body.label,
            scopes=body.scopes,
            rate_limit_per_minute=body.rate_limit_per_minute,
            notes=body.notes,
        )
        conn.commit()

    logger.info("Admin created API key id=%s label=%s", key_id, body.label)
    return {"id": key_id, "key": raw_key, "prefix": prefix, "label": body.label}


@router.post("/api-keys/{key_id}/revoke", dependencies=[Depends(require_admin)])
@limiter.limit(settings.RATE_LIMIT_ADMIN)
def revoke_api_key(request: Request, key_id: str) -> dict[str, Any]:
    """Revoke a key — no physical deletion, `revoked` is a one-way flag."""
    from app.db.connection import db_transaction
    from app.db.repositories.api_keys import ApiKeyRepository

    with db_transaction() as conn:
        revoked = ApiKeyRepository(conn).revoke(key_id)
        conn.commit()

    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found or already revoked")

    logger.info("Admin revoked API key id=%s", key_id)
    return {"id": key_id, "revoked": True}

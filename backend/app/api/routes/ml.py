"""ML model endpoints — status, active model, and training job enqueueing."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from redis import Redis
from rq import Queue

from app.api.dependencies import require_admin
from app.core.config import settings
from app.core.limiter import limiter
from app.db.connection import db_transaction
from app.db.repositories.jobs import JobRepository
from app.db.repositories.ml import MLRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ml", tags=["ml"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class TrainRequest(BaseModel):
    algorithm: str = Field(default="lightgbm", pattern="^(lightgbm|xgboost|random_forest)$")
    train_start_year: int = Field(default=2010, ge=1990, le=2030)
    validation_split: float = Field(default=0.2, gt=0.0, lt=1.0)


# ---------------------------------------------------------------------------
# POST /api/ml/train  — enqueue ML training job (admin only)
# ---------------------------------------------------------------------------

@router.post("/train", dependencies=[Depends(require_admin)])
@limiter.limit(settings.RATE_LIMIT_ADMIN)
def enqueue_ml_training(request: Request, body: TrainRequest) -> dict[str, Any]:
    """Enqueue ML model training in the 'long' RQ queue."""
    from app.workers.tasks import run_ml_training_task

    with db_transaction() as conn:
        job_repo = JobRepository(conn)
        job_id = job_repo.create({
            "job_type": "ml_training",
            "status": "enqueued",
            "progress": 0.0,
        })
        conn.commit()

    redis_conn = Redis.from_url(settings.REDIS_URL)
    q = Queue("long", connection=redis_conn)
    rq_job = q.enqueue(
        run_ml_training_task,
        job_id,
        body.algorithm,
        body.train_start_year,
        body.validation_split,
        job_timeout=settings.RQ_LONG_TIMEOUT,
    )

    with db_transaction() as conn:
        JobRepository(conn).update_status(job_id, "enqueued", result_ref=rq_job.id)
        conn.commit()

    logger.info(
        "ML training enqueued: rq=%s db_job=%s algo=%s",
        rq_job.id, job_id, body.algorithm,
    )
    return {
        "job_id": job_id,
        "rq_job_id": rq_job.id,
        "algorithm": body.algorithm,
        "status": "enqueued",
    }


# ---------------------------------------------------------------------------
# GET /api/ml/models/active  — return the currently active model
# ---------------------------------------------------------------------------

@router.get("/models/active")
def get_active_model() -> dict[str, Any]:
    """Return metadata for the currently active ML model."""
    with db_transaction() as conn:
        row = MLRepository(conn).get_best_model()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active ML model found. Run /api/ml/train first.",
        )
    return row


# ---------------------------------------------------------------------------
# GET /api/ml/models  — list all trained models
# ---------------------------------------------------------------------------

@router.get("/models")
def list_models() -> list[dict[str, Any]]:
    """Return all trained ML models ordered by Brier score."""
    with db_transaction() as conn:
        return MLRepository(conn).list_models()


# ---------------------------------------------------------------------------
# GET /api/ml/history  — last N trained models with metrics
# ---------------------------------------------------------------------------

@router.get("/history", dependencies=[Depends(require_admin)])
def ml_history(limit: int = 10) -> list[dict[str, Any]]:
    """Return the last *limit* trained ML models ordered by recency (admin only)."""
    with db_transaction() as conn:
        rows = conn.execute(
            """
            SELECT m.id, m.algorithm, m.brier_score, m.log_loss, m.accuracy,
                   m.is_active, m.model_path, m.created_at,
                   r.train_start_year, r.status AS run_status
              FROM ml_models m
         LEFT JOIN ml_training_runs r ON m.training_run_id = r.id
             ORDER BY m.created_at DESC
             LIMIT ?
            """,
            (max(1, min(limit, 50)),),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /api/ml/predict/{home_team_id}/{away_team_id}  — single-match prediction
# ---------------------------------------------------------------------------

@router.get("/predict/{home_team_id}/{away_team_id}")
def predict_match(
    home_team_id: str,
    away_team_id: str,
    is_neutral: bool = True,
) -> dict[str, Any]:
    """Return ML-calibrated prediction for a single match."""
    
    from app.services.prediction.ml_calibrated import get_cached_model
    with db_transaction() as conn:
        model = get_cached_model(conn)
        result = model.predict_match(
            home_team_id, away_team_id,
            context={"is_neutral": is_neutral},
        )
    return result

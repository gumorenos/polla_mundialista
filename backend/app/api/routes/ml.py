"""ML model endpoints — status, active model, and training job enqueueing."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field
from redis import Redis
from rq import Queue

from app.core.config import settings
from app.db.connection import db_transaction
from app.db.repositories.jobs import JobRepository
from app.db.repositories.ml import MLRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ml", tags=["ml"])


def _require_admin(x_admin_token: str | None) -> None:
    if not settings.ADMIN_TOKEN:
        return
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-Admin-Token",
        )


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

@router.post("/train")
def enqueue_ml_training(
    body: TrainRequest,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Enqueue ML model training in the 'long' RQ queue."""
    from app.workers.tasks import run_ml_training_task

    _require_admin(x_admin_token)

    with db_transaction() as conn:
        job_repo = JobRepository(conn)
        job_id = job_repo.create({
            "job_type": "ml_training",
            "status":   "enqueued",
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
        "job_id":     job_id,
        "rq_job_id":  rq_job.id,
        "algorithm":  body.algorithm,
        "status":     "enqueued",
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
# GET /api/ml/predict/{home_team_id}/{away_team_id}  — single-match prediction
# ---------------------------------------------------------------------------

@router.get("/predict/{home_team_id}/{away_team_id}")
def predict_match(
    home_team_id: str,
    away_team_id: str,
    is_neutral: bool = True,
) -> dict[str, Any]:
    """Return ML-calibrated prediction for a single match."""
    from app.services.prediction.ml_calibrated import MLCalibratedModel

    with db_transaction() as conn:
        model = MLCalibratedModel(conn)
        result = model.predict_match(
            home_team_id, away_team_id,
            context={"is_neutral": is_neutral},
        )
    return result

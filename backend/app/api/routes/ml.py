"""ML model endpoints — status, active model, and training job enqueueing."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
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


def _public_model(row: dict[str, Any]) -> dict[str, Any]:
    """Remove filesystem metadata from public ML model responses."""
    return {k: v for k, v in row.items() if k != "model_path"}


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

    try:
        with db_transaction() as conn:
            JobRepository(conn).update_rq_job_id(job_id, rq_job.id)
            conn.commit()
    except Exception:
        logger.exception("ML training enqueued in RQ but rq_job_id update failed: db_job=%s rq=%s", job_id, rq_job.id)

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
    return _public_model(row)


# ---------------------------------------------------------------------------
# GET /api/ml/models  — list all trained models
# ---------------------------------------------------------------------------

@router.get("/models")
def list_models() -> list[dict[str, Any]]:
    """Return all trained ML models ordered by Brier score."""
    with db_transaction() as conn:
        return [_public_model(row) for row in MLRepository(conn).list_models()]


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


# ---------------------------------------------------------------------------
# GET /api/ml/shap/global  — global feature importance from active model
# ---------------------------------------------------------------------------

@router.get("/shap/global")
def get_shap_global() -> dict[str, Any]:
    """Return global SHAP feature importance from the active ML model."""
    import json

    from app.services.ml.shap_service import FEATURE_META

    with db_transaction() as conn:
        row = MLRepository(conn).get_active_shap_importance()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active ML model found. Run /api/ml/train first.",
        )

    raw_shap = row.get("shap_importance")
    if not raw_shap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SHAP importance not computed for this model. Retrain to generate SHAP data.",
        )

    importance_map: dict[str, float] = json.loads(raw_shap)
    features = [
        {
            "feature":    feat,
            "label":      FEATURE_META.get(feat, {}).get("label", feat),
            "importance": round(imp, 6),
        }
        for feat, imp in importance_map.items()
    ]

    return {
        "model_id":  row["id"],
        "algorithm": row["algorithm"],
        "features":  features,
    }


# ---------------------------------------------------------------------------
# GET /api/ml/shap  — per-match SHAP explanation
# ---------------------------------------------------------------------------

@router.get("/shap")
def get_shap_match(
    home: str = Query(..., description="Home team ID"),
    away: str = Query(..., description="Away team ID"),
    is_neutral: bool = Query(default=True),
) -> dict[str, Any]:
    """Return SHAP explanation for a single match using the active ML model."""
    from app.services.ml.feature_builder import FEATURE_NAMES, build_match_features
    from app.services.ml.shap_service import explain_match
    from app.services.prediction.ml_calibrated import _safe_load_model

    with db_transaction() as conn:
        repo = MLRepository(conn)
        model_row = repo.get_best_model()
        if not model_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active ML model found. Run /api/ml/train first.",
            )

        features, missing = build_match_features(home, away, conn, is_neutral)

    model_path = model_row.get("model_path")
    if not model_path:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Active model has no file path.",
        )

    try:
        clf = _safe_load_model(model_path)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not load model file: {exc}",
        )

    import pandas as pd
    X = pd.DataFrame([features], columns=FEATURE_NAMES)
    proba = clf.predict_proba(X)[0]
    prediction = {
        "home_win": round(float(proba[0]), 4),
        "draw":     round(float(proba[1]), 4),
        "away_win": round(float(proba[2]), 4),
    }

    explanation = explain_match(clf, features, FEATURE_NAMES, home, away, prediction)

    return {
        "home_team":    home,
        "away_team":    away,
        "is_neutral":   is_neutral,
        "features_missing": missing,
        "prediction":   prediction,
        "explanation":  explanation,
    }

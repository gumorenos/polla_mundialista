"""Evaluation endpoints — model metrics summary and calibration data."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import settings
from app.db.connection import db_transaction
from app.db.repositories.evaluations import EvaluationRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])


# ---------------------------------------------------------------------------
# GET /api/evaluations/summary
# ---------------------------------------------------------------------------

@router.get("/summary")
def get_summary() -> list[dict[str, Any]]:
    """Return aggregate metrics per model normalised to the frontend contract."""
    with db_transaction() as conn:
        repo = EvaluationRepository(conn)
        model_names = [
            r["model_name"]
            for r in conn.execute(
                "SELECT DISTINCT model_name FROM model_evaluations ORDER BY model_name"
            ).fetchall()
        ]
        raw = [repo.compute_aggregate_metrics(m) for m in model_names if m]

    # Normalise avg_* keys → frontend contract (brier_score, log_loss, rps, accuracy)
    return [
        {
            "model_name": row.get("model_name"),
            "brier_score": row.get("avg_brier"),
            "log_loss": row.get("avg_log_loss"),
            "rps": row.get("avg_rps"),
            "accuracy": row.get("avg_accuracy"),
            "total_predictions": row.get("n_evaluations", 0),
        }
        for row in raw
        if row
    ]


# ---------------------------------------------------------------------------
# GET /api/evaluations/calibration?model={name}
# ---------------------------------------------------------------------------

@router.get("/calibration")
def get_calibration(
    model: str = Query(..., description="Model name, e.g. 'poisson'"),
) -> list[dict[str, Any]]:
    """Return calibration data for a specific model from the last export."""
    exports_dir = Path(settings.DATA_EXPORTS_PATH)
    cal_path = exports_dir / f"calibration_{model}.json"

    if not cal_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No calibration data found for model '{model}'. "
                "Run /api/pipelines/full-refresh first."
            ),
        )

    try:
        return json.loads(cal_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Error reading calibration file %s: %s", cal_path, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read calibration data",
        ) from exc


# ---------------------------------------------------------------------------
# GET /api/evaluations/{model_name}  — full evaluation history for a model
# ---------------------------------------------------------------------------

@router.get("/{model_name}")
def get_evaluations_for_model(model_name: str) -> list[dict[str, Any]]:
    """Return all evaluation records for a specific model."""
    with db_transaction() as conn:
        rows = EvaluationRepository(conn).get_by_model(model_name)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No evaluations found for model '{model_name}'",
        )
    return rows

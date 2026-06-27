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
# GET /api/evaluations/radar
# ---------------------------------------------------------------------------

@router.get("/radar")
def get_radar() -> dict[str, Any]:
    """Return normalised metrics for a RadarChart comparison across all models.

    Normalisation convention (all axes: higher = better):
      - Brier, LogLoss, RPS (lower is better): 1 - (v - min) / (max - min)
      - Accuracy (higher is better):            (v - min) / (max - min)

    When only one model has data, all normalised values are 1.0.
    Raw values are also returned so the frontend can show them in tooltips.
    """
    with db_transaction() as conn:
        repo = EvaluationRepository(conn)
        model_names = [
            r["model_name"]
            for r in conn.execute(
                "SELECT DISTINCT model_name FROM model_evaluations ORDER BY model_name"
            ).fetchall()
        ]
        raw_rows = {m: repo.compute_aggregate_metrics(m) for m in model_names if m}

    # Drop models that returned no data
    raw_rows = {m: r for m, r in raw_rows.items() if r}

    METRICS = ["brier_score", "log_loss", "rps", "accuracy"]
    LOWER_IS_BETTER = {"brier_score", "log_loss", "rps"}

    # Collect per-metric values
    metric_vals: dict[str, dict[str, float]] = {met: {} for met in METRICS}
    for model, row in raw_rows.items():
        metric_vals["brier_score"][model] = row.get("avg_brier") or 0.0
        metric_vals["log_loss"][model]    = row.get("avg_log_loss") or 0.0
        metric_vals["rps"][model]         = row.get("avg_rps") or 0.0
        metric_vals["accuracy"][model]    = row.get("avg_accuracy") or 0.0

    def _normalise(vals: dict[str, float], lower_is_better: bool) -> dict[str, float]:
        if not vals:
            return {}
        mn = min(vals.values())
        mx = max(vals.values())
        span = mx - mn
        result: dict[str, float] = {}
        for m, v in vals.items():
            if span == 0:
                result[m] = 1.0
            elif lower_is_better:
                result[m] = round(1.0 - (v - mn) / span, 4)
            else:
                result[m] = round((v - mn) / span, 4)
        return result

    normalised: dict[str, dict[str, float]] = {
        met: _normalise(metric_vals[met], met in LOWER_IS_BETTER)
        for met in METRICS
    }

    # Transpose: model → [brier_norm, log_loss_norm, rps_norm, acc_norm]
    models_out: dict[str, list[float]] = {}
    raw_out: dict[str, list[float | None]] = {}
    for model in raw_rows:
        models_out[model] = [normalised[met].get(model, 0.0) for met in METRICS]
        raw_out[model] = [
            metric_vals[met].get(model) for met in METRICS
        ]

    return {
        "metrics": ["Brier ↓", "LogLoss ↓", "RPS ↓", "Accuracy ↑"],
        "models":  models_out,
        "raw":     raw_out,
    }


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

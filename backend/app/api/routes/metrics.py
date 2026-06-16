"""System metrics endpoint — health and status overview for monitoring."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from app.api.dependencies import require_admin
from app.db.connection import db_transaction

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["metrics"])


def _fetch_metrics(conn) -> dict[str, Any]:
    """Collect all metrics from DB into a single dict."""
    latest_sim = conn.execute(
        "SELECT MAX(finished_at) AS ts FROM simulation_runs WHERE status = 'completed'"
    ).fetchone()["ts"]

    latest_ml = conn.execute(
        "SELECT MAX(finished_at) AS ts FROM ml_training_runs WHERE status = 'completed'"
    ).fetchone()["ts"]

    latest_news = conn.execute(
        "SELECT MAX(created_at) AS ts FROM availability_claims"
    ).fetchone()["ts"]

    jobs_running = conn.execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE status IN ('enqueued', 'running', 'started')"
    ).fetchone()["n"]

    jobs_failed = conn.execute(
        """
        SELECT COUNT(*) AS n FROM jobs
        WHERE status = 'failed'
          AND finished_at >= datetime('now', '-24 hours')
        """
    ).fetchone()["n"]

    injury_rows = conn.execute(
        """
        SELECT DISTINCT t.name AS team_name, ac.player_name, ac.status AS injury_status
        FROM availability_claims ac
        JOIN teams t ON ac.team_id = t.id
        WHERE ac.affects_prediction = 1
          AND ac.status IN ('injured', 'doubtful', 'unavailable')
          AND ac.created_at >= datetime('now', '-7 days')
        ORDER BY t.name, ac.player_name
        """
    ).fetchall()
    teams_with_injuries = [dict(r) for r in injury_rows]

    ml_row = conn.execute(
        "SELECT COUNT(*) AS total, SUM(is_active) AS active FROM ml_models"
    ).fetchone()

    total_ml = ml_row["total"] or 0
    active_ml = ml_row["active"] or 0
    if total_ml == 0:
        ml_status = "untrained"
    elif active_ml > 0:
        ml_status = "active"
    else:
        ml_status = "degraded"

    return {
        "latest_simulation_at": latest_sim,
        "latest_ml_training_at": latest_ml,
        "latest_news_analysis_at": latest_news,
        "jobs_running": jobs_running,
        "jobs_failed_last_24h": jobs_failed,
        "teams_with_injuries": teams_with_injuries,
        "model_status": {
            "baseline": "ok",
            "elo": "ok",
            "poisson": "ok",
            "poisson_context": "ok",
            "ml_calibrated": ml_status,
        },
    }


@router.get("/metrics")
def get_metrics() -> dict[str, Any]:
    """Public health snapshot — no sensitive operational data."""
    with db_transaction() as conn:
        data = _fetch_metrics(conn)
    return {
        "latest_simulation_at": data["latest_simulation_at"],
        "jobs_running": data["jobs_running"],
        "model_status": data["model_status"],
    }


@router.get("/metrics/admin", dependencies=[Depends(require_admin)])
def get_metrics_admin() -> dict[str, Any]:
    """Full metrics including injury data and ML training timestamps (admin only)."""
    with db_transaction() as conn:
        return _fetch_metrics(conn)

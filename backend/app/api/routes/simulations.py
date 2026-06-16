"""Simulation endpoints — enqueue Monte Carlo runs and query results."""

from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from redis import Redis
from rq import Queue

from app.api.dependencies import require_admin
from app.core.config import settings
from app.core.limiter import limiter
from app.db.connection import db_transaction
from app.db.repositories.jobs import JobRepository
from app.db.repositories.simulations import SimulationRepository
from app.workers.tasks import run_simulation_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/simulations", tags=["simulations"])


ModelName = Literal["baseline", "elo", "poisson", "poisson_context", "ml_calibrated"]


class RunRequest(BaseModel):
    model_name: ModelName = "poisson"
    iterations: int = Field(default=None, ge=1_000, le=100_000)


# ---------------------------------------------------------------------------
# POST /api/simulations/run
# ---------------------------------------------------------------------------

@router.post("/run", dependencies=[Depends(require_admin)])
@limiter.limit(settings.RATE_LIMIT_ADMIN)
def enqueue_simulation(request: Request, body: RunRequest) -> dict[str, Any]:
    """Enqueue a Monte Carlo simulation run in the 'long' RQ queue."""
    iterations = body.iterations or settings.MONTECARLO_ITERATIONS
    seed = settings.MONTECARLO_SEED

    with db_transaction() as conn:
        job_repo = JobRepository(conn)
        job_id = job_repo.create({
            "job_type": f"simulation_{body.model_name}",
            "status":   "enqueued",
            "progress": 0.0,
        })
        conn.commit()

    redis_conn = Redis.from_url(settings.REDIS_URL)
    q = Queue("long", connection=redis_conn)
    rq_job = q.enqueue(
        run_simulation_task,
        body.model_name,
        iterations,
        seed,
        job_id,
        job_timeout=settings.RQ_LONG_TIMEOUT,
    )

    with db_transaction() as conn:
        JobRepository(conn).update_status(job_id, "enqueued",
                                          result_ref=rq_job.id)
        conn.commit()

    return {
        "job_id":     job_id,
        "rq_job_id":  rq_job.id,
        "model_name": body.model_name,
        "iterations": iterations,
        "status":     "enqueued",
    }


# ---------------------------------------------------------------------------
# GET /api/simulations/comparison
# ---------------------------------------------------------------------------

_COMPARISON_MODELS = ["baseline", "elo", "poisson", "poisson_context", "ml_calibrated"]


@router.get("/comparison")
def get_comparison() -> dict[str, Any]:
    """Return win_tournament % for each team across all models (latest completed run per model).

    Only includes teams that appear in at least one completed simulation.
    Missing model data for a team is returned as null.
    """
    with db_transaction() as conn:
        rows = conn.execute(
            """
            WITH latest_runs AS (
                SELECT model_name, MAX(finished_at) AS max_finished
                FROM simulation_runs
                WHERE status = 'completed'
                GROUP BY model_name
            ),
            run_ids AS (
                SELECT sr.id, sr.model_name
                FROM simulation_runs sr
                JOIN latest_runs lr
                    ON sr.model_name = lr.model_name
                    AND sr.finished_at = lr.max_finished
                WHERE sr.status = 'completed'
            )
            SELECT
                str.team_id,
                t.name AS team_name,
                ri.model_name,
                str.win_tournament
            FROM simulation_team_results str
            JOIN run_ids ri ON str.simulation_run_id = ri.id
            JOIN teams t ON str.team_id = t.id
            ORDER BY str.team_id, ri.model_name
            """
        ).fetchall()

    # Pivot into {team_id: {model_name: win_tournament, ...}}
    teams_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        tid = row["team_id"]
        if tid not in teams_map:
            teams_map[tid] = {"team_id": tid, "team_name": row["team_name"]}
        teams_map[tid][row["model_name"]] = round(float(row["win_tournament"]), 4)

    # Fill missing models with None
    for entry in teams_map.values():
        for m in _COMPARISON_MODELS:
            entry.setdefault(m, None)

    # Sort by average win_tournament across present models (desc)
    def _avg(entry: dict[str, Any]) -> float:
        vals = [entry[m] for m in _COMPARISON_MODELS if entry[m] is not None]
        return sum(vals) / len(vals) if vals else 0.0

    teams_sorted = sorted(teams_map.values(), key=_avg, reverse=True)

    return {
        "models": _COMPARISON_MODELS,
        "teams": teams_sorted,
    }


# ---------------------------------------------------------------------------
# GET /api/simulations/latest
# ---------------------------------------------------------------------------

@router.get("/latest")
def get_latest(model: str = Query(default="poisson")) -> dict[str, Any]:
    """Return latest completed simulation results for a model."""
    with db_transaction() as conn:
        repo = SimulationRepository(conn)
        run = repo.get_latest_by_model(model)
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No completed simulation found for model '{model}'",
            )
        return repo.get_run_summary(run["id"])


# ---------------------------------------------------------------------------
# GET /api/simulations/{run_id}
# ---------------------------------------------------------------------------

@router.get("/{run_id}")
def get_simulation(run_id: str) -> dict[str, Any]:
    """Return results for a specific simulation run."""
    with db_transaction() as conn:
        repo = SimulationRepository(conn)
        summary = repo.get_run_summary(run_id)
        if not summary:
            raise HTTPException(status_code=404, detail="Simulation run not found")
        return summary


# ---------------------------------------------------------------------------
# GET /api/simulations/{run_id}/bracket
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# GET /api/simulations/{run_id}/bracket
# ---------------------------------------------------------------------------

@router.get("/{run_id}/bracket")
def get_bracket(run_id: str) -> dict[str, Any]:
    """Return a single deterministic bracket simulation for visualisation."""
    from app.services.simulation.monte_carlo import _init_model, _load_groups
    from app.services.simulation.wc2026_bracket import WC2026Bracket

    with db_transaction() as conn:
        repo = SimulationRepository(conn)
        run_row = conn.execute(
            "SELECT model_name, seed FROM simulation_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if run_row is None:
            raise HTTPException(status_code=404, detail="Simulation run not found")

        model  = _init_model(run_row["model_name"], conn)
        groups = _load_groups(conn)
        rng    = np.random.default_rng(run_row["seed"])

        bracket = WC2026Bracket(model, groups, rng)
        result  = bracket.run()

    return {
        "run_id":        run_id,
        "champion":      result["champion"],
        "runner_up":     result["runner_up"],
        "third":         result["third"],
        "fourth":        result["fourth"],
        "rounds_reached": result["rounds_reached"],
    }

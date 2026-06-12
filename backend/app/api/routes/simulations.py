"""Simulation endpoints — enqueue Monte Carlo runs and query results."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from redis import Redis
from rq import Queue

from app.core.config import settings
from app.db.connection import db_transaction
from app.db.repositories.jobs import JobRepository
from app.db.repositories.simulations import SimulationRepository
from app.workers.tasks import run_simulation_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/simulations", tags=["simulations"])


class RunRequest(BaseModel):
    model_name: str = "poisson"
    iterations: int = Field(default=None, gt=0, le=100_000)


# ---------------------------------------------------------------------------
# POST /api/simulations/run
# ---------------------------------------------------------------------------

@router.post("/run")
def enqueue_simulation(body: RunRequest) -> dict[str, Any]:
    """Enqueue a Monte Carlo simulation run in the 'long' RQ queue."""
    iterations = body.iterations or settings.MONTECARLO_ITERATIONS
    seed = settings.MONTECARLO_SEED

    with db_transaction() as conn:
        job_repo = JobRepository(conn)
        job_id = job_repo.create({
            "job_type": "simulation",
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

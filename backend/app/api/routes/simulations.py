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
from app.workers.tasks import run_bracket_simulation_task, run_simulation_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/simulations", tags=["simulations"])


ModelName = Literal["baseline", "elo", "poisson", "poisson_context", "ml_calibrated", "consensus"]


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
            "job_type": f"simulation_full_{body.model_name}",
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

    try:
        with db_transaction() as conn:
            JobRepository(conn).update_rq_job_id(job_id, rq_job.id)
            conn.commit()
    except Exception:
        logger.exception("Simulation job enqueued in RQ but rq_job_id update failed: db_job=%s rq=%s", job_id, rq_job.id)

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

_COMPARISON_MODELS = ["baseline", "elo", "poisson", "poisson_context", "ml_calibrated", "consensus"]


@router.get("/comparison")
def get_comparison() -> dict[str, Any]:
    """Return win_tournament % for each team across all models (latest VALID
    completed run per model — see app.services.simulation.validation).

    Only includes teams that appear in at least one completed simulation.
    Missing model data for a team is returned as null.
    """
    from app.services.simulation.validation import get_latest_valid_run

    with db_transaction() as conn:
        valid_run_ids = []
        for model_name in _COMPARISON_MODELS:
            run = get_latest_valid_run(conn, model_name)
            if run is not None:
                valid_run_ids.append(run["id"])

        if not valid_run_ids:
            return {"models": _COMPARISON_MODELS, "teams": []}

        placeholders = ",".join("?" for _ in valid_run_ids)
        rows = conn.execute(
            f"""
            SELECT
                str.team_id,
                t.name AS team_name,
                sr.model_name,
                str.win_tournament
            FROM simulation_team_results str
            JOIN simulation_runs sr ON sr.id = str.simulation_run_id
            JOIN teams t ON str.team_id = t.id
            WHERE sr.id IN ({placeholders})
            ORDER BY str.team_id, sr.model_name
            """,
            valid_run_ids,
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
# GET /api/simulations/history/{team_id}
# ---------------------------------------------------------------------------

@router.get("/history/{team_id}")
def get_team_history(
    team_id: str,
    model: str = Query(default="poisson"),
    limit: int = Query(default=20, ge=2, le=100),
) -> dict[str, Any]:
    """Return simulation history for one team — champion/top4/top16 probability per run.

    Returns empty history list (not an error) when fewer than 2 data points exist.
    """
    with db_transaction() as conn:
        team_row = conn.execute(
            "SELECT id, name FROM teams WHERE id = ?", (team_id,)
        ).fetchone()
        if not team_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Team '{team_id}' not found",
            )

        rows = conn.execute(
            """
            SELECT
                sr.id          AS run_id,
                sr.finished_at AS created_at,
                str.win_tournament   AS champion_prob,
                str.reach_semi_final AS top4_prob,
                str.reach_round_of_16 AS top16_prob
            FROM simulation_runs sr
            JOIN simulation_team_results str
                ON str.simulation_run_id = sr.id
            WHERE str.team_id  = ?
              AND sr.model_name = ?
              AND sr.status     = 'completed'
              AND sr.finished_at IS NOT NULL
            ORDER BY sr.finished_at ASC
            LIMIT ?
            """,
            (team_id, model, limit),
        ).fetchall()

    history = [
        {
            "run_id":        r["run_id"],
            "created_at":    r["created_at"],
            "champion_prob": round(float(r["champion_prob"]), 4),
            "top4_prob":     round(float(r["top4_prob"]),     4),
            "top16_prob":    round(float(r["top16_prob"]),    4),
        }
        for r in rows
    ]

    return {
        "team_id":   team_id,
        "team_name": team_row["name"],
        "model":     model,
        "history":   history if len(history) >= 2 else [],
    }


# ---------------------------------------------------------------------------
# GET /api/simulations/favorite-history
# ---------------------------------------------------------------------------

@router.get("/favorite-history")
def get_favorite_history(
    model: str = Query(default="poisson"),
    limit: int = Query(default=20, ge=2, le=100),
) -> dict[str, Any]:
    """Return the evolution of the #1 team's champion probability over time for a model.

    Each entry shows which team was the leader at that simulation run
    and their champion probability. Useful for detecting if the favourite changed.
    """
    with db_transaction() as conn:
        rows = conn.execute(
            """
            WITH ranked AS (
                SELECT
                    sr.id          AS run_id,
                    sr.finished_at AS created_at,
                    str.team_id,
                    t.name         AS team_name,
                    str.win_tournament AS champion_prob,
                    ROW_NUMBER() OVER (
                        PARTITION BY sr.id
                        ORDER BY str.win_tournament DESC
                    ) AS rn
                FROM simulation_runs sr
                JOIN simulation_team_results str ON str.simulation_run_id = sr.id
                JOIN teams t ON t.id = str.team_id
                WHERE sr.model_name = ?
                  AND sr.status     = 'completed'
                  AND sr.finished_at IS NOT NULL
            )
            SELECT run_id, created_at, team_id, team_name, champion_prob
            FROM ranked
            WHERE rn = 1
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (model, limit),
        ).fetchall()

    history = [
        {
            "run_id":        r["run_id"],
            "created_at":    r["created_at"],
            "team_id":       r["team_id"],
            "team_name":     r["team_name"],
            "champion_prob": round(float(r["champion_prob"]), 4),
        }
        for r in rows
    ]

    return {"model": model, "history": history if len(history) >= 2 else []}


# ---------------------------------------------------------------------------
# GET /api/simulations/latest
# ---------------------------------------------------------------------------

@router.get("/latest")
def get_latest(model: str = Query(default="poisson")) -> dict[str, Any]:
    """Return latest VALID completed simulation results for a model.

    Scans past a stale/invalid latest run (see app.services.simulation.validation)
    rather than serving data known to violate the probability invariants.
    """
    from app.services.simulation.validation import get_latest_valid_run

    with db_transaction() as conn:
        repo = SimulationRepository(conn)
        run = get_latest_valid_run(conn, model)
        if not run:
            history = repo.list_runs_history(model, limit=50)
            n_other = len(history)
            detail = (
                f"No hay simulación válida reciente para el modelo '{model}'; "
                f"existen {n_other} runs inválidos/antiguos. Recalcula el modelo."
                if n_other else
                f"No valid completed simulation found for model '{model}'. Recalcula el modelo."
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        return repo.get_run_summary(run["id"])


# ---------------------------------------------------------------------------
# GET /api/simulations/runs
# ---------------------------------------------------------------------------

@router.get("/runs")
def list_simulation_runs(
    model: str = Query(default="poisson"),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """History of simulation runs for a model, any status, newest first.

    Unlike /latest (which only ever returns a valid completed run), this
    never filters out invalid/failed runs — the Simulations screen uses it
    to show run history with status badges instead of going blank when the
    guardrail script has invalidated the latest completed runs.
    """
    with db_transaction() as conn:
        repo = SimulationRepository(conn)
        runs = repo.list_runs_history(model, limit=limit)
    return {"model": model, "runs": runs}


# ---------------------------------------------------------------------------
# GET /api/simulations/diff
# ---------------------------------------------------------------------------

@router.get("/diff")
def get_simulation_diff(model: str = Query(default="poisson")) -> dict[str, Any]:
    """Compare the two most recent completed simulations for a model."""
    from datetime import datetime, timezone

    with db_transaction() as conn:
        repo = SimulationRepository(conn)
        runs = repo.get_two_latest_by_model(model)

        if len(runs) < 2:
            return {
                "error": "no_previous_simulation",
                "message": "Solo hay una simulación disponible para comparar",
            }

        current_run  = runs[0]
        previous_run = runs[1]

        cur_map  = {r["team_id"]: r for r in repo.get_team_results_by_run(current_run["id"])}
        prev_map = {r["team_id"]: r for r in repo.get_team_results_by_run(previous_run["id"])}

        teams: list[dict[str, Any]] = []
        for team_id, cur in cur_map.items():
            if team_id not in prev_map:
                continue
            prev = prev_map[team_id]

            champion_delta = float(cur["win_tournament"]) - float(prev["win_tournament"])
            top4_delta     = float(cur["reach_semi_final"])   - float(prev["reach_semi_final"])
            top16_delta    = float(cur["reach_round_of_16"])  - float(prev["reach_round_of_16"])

            if abs(champion_delta) < 0.005:
                trend = "stable"
            elif champion_delta > 0:
                trend = "up"
            else:
                trend = "down"

            teams.append({
                "team_id":           team_id,
                "team_name":         cur["team_name"],
                "current_champion":  round(float(cur["win_tournament"]),    4),
                "previous_champion": round(float(prev["win_tournament"]),   4),
                "champion_delta":    round(champion_delta,                  4),
                "current_top4":      round(float(cur["reach_semi_final"]),  4),
                "previous_top4":     round(float(prev["reach_semi_final"]), 4),
                "top4_delta":        round(top4_delta,                      4),
                "current_top16":     round(float(cur["reach_round_of_16"]),  4),
                "previous_top16":    round(float(prev["reach_round_of_16"]), 4),
                "top16_delta":       round(top16_delta,                      4),
                "trend":             trend,
            })

        teams.sort(key=lambda t: abs(t["champion_delta"]), reverse=True)

        def _parse_dt(s: str | None) -> datetime:
            if not s:
                return datetime.now(timezone.utc)
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except Exception:
                return datetime.now(timezone.utc)

        hours_between = round(
            (_parse_dt(current_run["finished_at"]) - _parse_dt(previous_run["finished_at"])).total_seconds() / 3600,
            1,
        )

        biggest_movers = teams[:5]

        summary_parts = [
            f"{t['team_name']} ({'+' if t['champion_delta'] >= 0 else ''}{t['champion_delta'] * 100:.1f}%)"
            for t in biggest_movers[:3]
        ]
        summary = (
            f"{', '.join(summary_parts)} son los mayores movimientos desde la última simulación."
            if summary_parts else "Sin cambios significativos."
        )

        return {
            "model":               model,
            "current_run_id":      current_run["id"],
            "previous_run_id":     previous_run["id"],
            "current_created_at":  current_run["finished_at"],
            "previous_created_at": previous_run["finished_at"],
            "hours_between":       hours_between,
            "teams":               teams,
            "biggest_movers":      biggest_movers,
            "summary":             summary,
        }


# ---------------------------------------------------------------------------
# Bracket routes — MUST be registered before /{run_id} (single dynamic
# segment) below, otherwise Starlette matches "/bracket" as run_id="bracket"
# and these handlers become unreachable dead code.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# POST /api/simulations/bracket/run
# ---------------------------------------------------------------------------

@router.post("/bracket/run", dependencies=[Depends(require_admin)])
@limiter.limit(settings.RATE_LIMIT_ADMIN)
def enqueue_bracket_simulation(request: Request, model: ModelName = Query(default="elo")) -> dict[str, Any]:
    """Enqueue a live-bracket simulation (real R32 qualifiers + pending matches only).

    If the tournament hasn't reached R32 yet, the job completes as 'skipped'
    (not 'failed') with a clear message — see run_bracket_simulation_task.
    """
    from app.core.job_helper import enqueue_job

    result = enqueue_job(
        "long", run_bracket_simulation_task, model, "manual",
        job_type=f"simulation_bracket_{model}", timeout=settings.RQ_LONG_TIMEOUT,
    )
    return {**result, "model_name": model}


# ---------------------------------------------------------------------------
# GET /api/simulations/bracket/latest
# ---------------------------------------------------------------------------

@router.get("/bracket/latest")
def get_bracket_latest(model: ModelName = Query(default="elo")) -> dict[str, Any]:
    """Latest completed bracket run for a model (new contract, replaces the
    legacy /bracket?model= alias kept below for backward compatibility)."""
    from app.services.simulation.bracket_simulator import get_latest_bracket_view

    with db_transaction() as conn:
        return get_latest_bracket_view(conn, model)


# ---------------------------------------------------------------------------
# GET /api/simulations/bracket/runs
# ---------------------------------------------------------------------------

@router.get("/bracket/runs")
def list_bracket_runs(
    model: ModelName = Query(default="elo"),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """Historical bracket runs for a model, most recent first."""
    from app.db.repositories.bracket import BracketRepository

    with db_transaction() as conn:
        runs = BracketRepository(conn).list_runs(model, limit=limit)
    return {"model": model, "runs": runs}


# ---------------------------------------------------------------------------
# GET /api/simulations/bracket/runs/{run_id}
# ---------------------------------------------------------------------------

@router.get("/bracket/runs/{run_id}")
def get_bracket_run(run_id: str) -> dict[str, Any]:
    """Full detail (metadata + per-round results) for one historical bracket run."""
    from app.db.repositories.bracket import BracketRepository

    with db_transaction() as conn:
        repo = BracketRepository(conn)
        run = repo.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Bracket run not found")

        rounds: dict[str, list[dict[str, Any]]] = {}
        for r in repo.get_run_results(run_id):
            rounds.setdefault(r["round_name"], []).append({
                "team_id":        r["team_id"],
                "team_name":      r["team_name"],
                "advance_prob":   round(float(r["advance_prob"]), 4),
                "opponent_id":    r["opponent_id"],
                "opponent_name":  r["opponent_name"],
                "match_win_prob": round(float(r["match_win_prob"]), 4) if r["match_win_prob"] is not None else None,
                "is_eliminated":  bool(r["is_eliminated"]),
            })

    return {**run, "rounds": rounds}


# ---------------------------------------------------------------------------
# GET /api/simulations/bracket — legacy alias of /bracket/latest, old flat shape
# ---------------------------------------------------------------------------

@router.get("/bracket")
def get_bracket_simulation(model: ModelName = Query(default="elo")) -> dict[str, Any]:
    """Legacy shape: {model, rounds, computed_at} — kept so the existing
    frontend (useBracketSimulation) keeps working. New consumers should use
    GET /bracket/latest for the richer {run_id, status, message, meta} contract."""
    from app.services.simulation.bracket_simulator import get_latest_bracket_view

    with db_transaction() as conn:
        view = get_latest_bracket_view(conn, model)

    return {"model": model, "rounds": view["rounds"], "computed_at": view["computed_at"]}


# ---------------------------------------------------------------------------
# GET /api/simulations/{run_id}/narrative/tournament
# GET /api/simulations/{run_id}/narrative/{team_id}
# ---------------------------------------------------------------------------

@router.get("/{run_id}/narrative/tournament")
def get_tournament_narrative(run_id: str) -> dict[str, Any]:
    """Return LLM narrative for the full tournament (lazily generated, cached 6 h)."""
    from app.db.repositories.narrative import NarrativeRepository
    from app.services.narrative.generator import generate_tournament_narrative

    with db_transaction() as conn:
        run_row = conn.execute(
            "SELECT model_name FROM simulation_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if run_row is None:
            raise HTTPException(status_code=404, detail="Simulation run not found")

        model_name = run_row["model_name"]
        repo = NarrativeRepository(conn)

        cached = repo.get_with_meta(run_id, model_name, None)
        if cached:
            return {"narrative": cached["narrative"], "generated_at": cached["generated_at"]}

        narrative = generate_tournament_narrative(conn, run_id)
        if narrative is None:
            return {"narrative": None, "generated_at": None}

        repo.save(run_id, model_name, narrative, team_id=None)
        conn.commit()
        row = repo.get_with_meta(run_id, model_name, None)
        generated_at = row["generated_at"] if row else None

    return {"narrative": narrative, "generated_at": generated_at}


@router.get("/{run_id}/narrative/{team_id}")
def get_team_narrative(run_id: str, team_id: str) -> dict[str, Any]:
    """Return LLM narrative for one team in this run (lazily generated, cached 6 h)."""
    from app.db.repositories.narrative import NarrativeRepository
    from app.services.narrative.generator import generate_team_narrative

    with db_transaction() as conn:
        run_row = conn.execute(
            "SELECT model_name FROM simulation_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if run_row is None:
            raise HTTPException(status_code=404, detail="Simulation run not found")

        model_name = run_row["model_name"]
        repo = NarrativeRepository(conn)

        cached = repo.get_with_meta(run_id, model_name, team_id)
        if cached:
            return {"narrative": cached["narrative"], "generated_at": cached["generated_at"]}

        narrative = generate_team_narrative(conn, run_id, team_id)
        if narrative is None:
            return {"narrative": None, "generated_at": None}

        repo.save(run_id, model_name, narrative, team_id=team_id)
        conn.commit()
        row = repo.get_with_meta(run_id, model_name, team_id)
        generated_at = row["generated_at"] if row else None

    return {"narrative": narrative, "generated_at": generated_at}


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

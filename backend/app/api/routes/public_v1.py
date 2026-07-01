"""Public read-only API v1 — for external consumption via API key.

Completely separate from the internal /api/* namespace: no require_admin,
no session cookies, GET-only. Auth is via X-API-Key (see
app.api.dependencies.require_api_key) checked against the api_keys table.

Response contract (see docs/public-api-v1.md):
  Success: {"data": ..., "meta": {generated_at, timezone, ...}}
  Error:   {"error": {"code", "message", "details"}}

The original endpoints (GET /teams, /groups, /fixtures, /simulations/{model},
/bracket/{model}) predate this envelope and are kept as-is (flat shape) for
backward compatibility — they are documented as legacy aliases. New
endpoints (/simulations/latest, /simulations/comparison, /bracket/latest,
/bracket/runs, /health, /metadata) use the enveloped contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import require_api_key
from app.core.config import settings
from app.core.limiter import limiter
from app.db.connection import db_transaction
from app.db.repositories.simulations import SimulationRepository

router = APIRouter(
    prefix="/api/public/v1",
    tags=["public-api"],
    dependencies=[Depends(require_api_key)],
)

_VALID_MODELS = {"baseline", "elo", "poisson", "poisson_context", "ml_calibrated", "consensus"}
_TIMEZONE_LABEL = "America/Lima"


def _error(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


def _envelope(data: Any, **meta: Any) -> dict[str, Any]:
    return {
        "data": data,
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "timezone": _TIMEZONE_LABEL,
            **meta,
        },
    }


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@router.get("/health")
@limiter.limit(settings.RATE_LIMIT_PUBLIC_API)
def public_health(request: Request) -> dict[str, Any]:
    """Liveness check for external consumers — requires a valid API key like
    every other endpoint in this namespace (no anonymous access)."""
    return _envelope({"status": "ok"})


# ---------------------------------------------------------------------------
# GET /metadata
# ---------------------------------------------------------------------------

@router.get("/metadata")
@limiter.limit(settings.RATE_LIMIT_PUBLIC_API)
def public_metadata(request: Request) -> dict[str, Any]:
    """Static contract info for external integrators — valid models, round
    names, and where to find the full docs. Never exposes secrets/keys."""
    return _envelope({
        "version": "v1",
        "models": sorted(_VALID_MODELS),
        "default_model": "consensus",
        "rounds": ["round_of_32", "round_of_16", "quarterfinals", "semifinals", "final", "champion"],
        "rate_limit": settings.RATE_LIMIT_PUBLIC_API,
        "docs": "docs/public-api-v1.md",
    })


# ---------------------------------------------------------------------------
# GET /teams  (legacy flat shape, unchanged)
# ---------------------------------------------------------------------------

@router.get("/teams")
@limiter.limit(settings.RATE_LIMIT_PUBLIC_API)
def list_teams(request: Request) -> list[dict[str, Any]]:
    """List the 48 WC2026 qualified teams."""
    with db_transaction() as conn:
        rows = conn.execute(
            "SELECT id, name, code, confederation FROM teams "
            "WHERE is_wc2026 = 1 ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /groups  (legacy flat shape, unchanged)
# ---------------------------------------------------------------------------

@router.get("/groups")
@limiter.limit(settings.RATE_LIMIT_PUBLIC_API)
def list_groups(request: Request) -> dict[str, list[str]]:
    """List the 12 WC2026 groups with their team IDs."""
    with db_transaction() as conn:
        rows = conn.execute(
            "SELECT g.id AS group_id, gt.team_id FROM groups g "
            "JOIN group_teams gt ON g.id = gt.group_id "
            "ORDER BY g.id, gt.position"
        ).fetchall()
        groups: dict[str, list[str]] = {}
        for r in rows:
            groups.setdefault(r["group_id"], []).append(r["team_id"])
        return groups


# ---------------------------------------------------------------------------
# GET /simulations/latest  (new enveloped contract)
# ---------------------------------------------------------------------------

@router.get("/simulations/latest")
@limiter.limit(settings.RATE_LIMIT_PUBLIC_API)
def get_simulation_latest(request: Request, model: str = Query(default="consensus")) -> Any:
    """Latest completed simulation results for a model. Defaults to 'consensus'
    — the recommended model for external consumption (see docs/public-api-v1.md)."""
    from app.services.simulation.validation import get_latest_valid_run

    if model not in _VALID_MODELS:
        return _error(400, "invalid_model", f"Invalid model. Must be one of: {sorted(_VALID_MODELS)}")

    with db_transaction() as conn:
        repo = SimulationRepository(conn)
        run = get_latest_valid_run(conn, model)
        if not run:
            return _error(
                404, "no_valid_simulation",
                f"No hay simulación válida para el modelo {model}. Recalcula el modelo.",
            )
        summary = repo.get_run_summary(run["id"])

    return _envelope(
        summary, model=model, source_run_id=run["id"],
        cache_ttl_seconds=300, stale=False,
    )


# ---------------------------------------------------------------------------
# GET /simulations/comparison  (new enveloped contract)
# ---------------------------------------------------------------------------

@router.get("/simulations/comparison")
@limiter.limit(settings.RATE_LIMIT_PUBLIC_API)
def get_simulation_comparison(request: Request) -> dict[str, Any]:
    """Win_tournament % per team across all models — for apps that want to
    show model agreement/disagreement rather than a single model's view."""
    from app.api.routes.simulations import get_comparison

    data = get_comparison()
    return _envelope(data, cache_ttl_seconds=300, stale=False)


# ---------------------------------------------------------------------------
# GET /simulations/{model_name}  (legacy alias, flat shape)
# ---------------------------------------------------------------------------

@router.get("/simulations/{model_name}")
@limiter.limit(settings.RATE_LIMIT_PUBLIC_API)
def get_simulation(request: Request, model_name: str) -> Any:
    """Legacy alias of GET /simulations/latest?model=<model_name> — flat
    shape (no {data, meta} envelope). New integrations should use /latest."""
    from app.services.simulation.validation import get_latest_valid_run

    if model_name not in _VALID_MODELS:
        raise HTTPException(status_code=400, detail=f"Invalid model_name. Must be one of: {sorted(_VALID_MODELS)}")

    with db_transaction() as conn:
        repo = SimulationRepository(conn)
        run = get_latest_valid_run(conn, model_name)
        if not run:
            raise HTTPException(
                status_code=404,
                detail=f"No valid completed simulation for model '{model_name}'. Recalcula el modelo.",
            )
        return repo.get_run_summary(run["id"])


# ---------------------------------------------------------------------------
# GET /bracket/latest  (new enveloped contract)
# ---------------------------------------------------------------------------

@router.get("/bracket/latest")
@limiter.limit(settings.RATE_LIMIT_PUBLIC_API)
def get_bracket_latest(request: Request, model: str = Query(default="consensus")) -> Any:
    """Latest live-bracket run for a model — historical, not a fresh
    simulation triggered by this call (the public API is read-only)."""
    from app.services.simulation.bracket_simulator import get_latest_bracket_view

    if model not in _VALID_MODELS:
        return _error(400, "invalid_model", f"Invalid model. Must be one of: {sorted(_VALID_MODELS)}")

    with db_transaction() as conn:
        view = get_latest_bracket_view(conn, model)

    if view["status"] != "completed":
        return {
            "model": model, "run_id": None, "status": view["status"],
            "rounds": {}, "computed_at": None, "message": view["message"],
        }

    return {
        "model": model,
        "run_id": view["run_id"],
        "status": "completed",
        "rounds": view["rounds"],
        "computed_at": view["computed_at"],
        "meta": {**view["meta"], "cache_ttl_seconds": 300},
    }


# ---------------------------------------------------------------------------
# GET /bracket/runs  (new enveloped contract)
# ---------------------------------------------------------------------------

@router.get("/bracket/runs")
@limiter.limit(settings.RATE_LIMIT_PUBLIC_API)
def get_bracket_runs(
    request: Request,
    model: str = Query(default="consensus"),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """Historical bracket runs for a model, most recent first."""
    from app.db.repositories.bracket import BracketRepository

    if model not in _VALID_MODELS:
        return _error(400, "invalid_model", f"Invalid model. Must be one of: {sorted(_VALID_MODELS)}")

    with db_transaction() as conn:
        runs = BracketRepository(conn).list_runs(model, limit=limit)

    return _envelope({"model": model, "runs": runs})


# ---------------------------------------------------------------------------
# GET /bracket/{model_name}  (legacy alias, flat shape)
# ---------------------------------------------------------------------------

@router.get("/bracket/{model_name}")
@limiter.limit(settings.RATE_LIMIT_PUBLIC_API)
def get_bracket(request: Request, model_name: str) -> Any:
    """Legacy alias of GET /bracket/latest?model=<model_name> — flat shape."""
    from app.services.simulation.bracket_simulator import get_latest_bracket_view

    if model_name not in _VALID_MODELS:
        raise HTTPException(status_code=400, detail=f"Invalid model_name. Must be one of: {sorted(_VALID_MODELS)}")

    with db_transaction() as conn:
        view = get_latest_bracket_view(conn, model_name)

    if view["status"] != "completed":
        raise HTTPException(
            status_code=404,
            detail=(
                view["message"]
                or f"No bracket simulation found for model '{model_name}'. "
                   "El torneo puede no haber llegado aún a fase eliminatoria."
            ),
        )

    return {
        "model_name": model_name,
        "rounds": [
            {"round_name": round_name, **team}
            for round_name, teams in view["rounds"].items()
            for team in teams
        ],
    }


# ---------------------------------------------------------------------------
# GET /fixtures  (legacy flat shape, unchanged)
# ---------------------------------------------------------------------------

@router.get("/fixtures")
@limiter.limit(settings.RATE_LIMIT_PUBLIC_API)
def list_fixtures(request: Request) -> list[dict[str, Any]]:
    """WC2026 fixtures with results where the match has already been played.

    Knockout-round fixtures hold 'TBD' placeholders for home/away teams
    until the bracket resolves them — only group-stage fixtures and
    already-played knockout matches carry real team ids and scores.
    """
    with db_transaction() as conn:
        rows = conn.execute(
            """
            SELECT f.id, f.stage, f.group_id, f.home_team_id, f.away_team_id,
                   f.match_date, f.venue_id, r.home_goals, r.away_goals
            FROM fixtures f
            LEFT JOIN results r
                ON r.home_team_id = f.home_team_id
               AND r.away_team_id = f.away_team_id
               AND r.match_date   = f.match_date
            WHERE f.tournament = 'WC2026'
            ORDER BY f.match_date
            """
        ).fetchall()
        return [dict(r) for r in rows]

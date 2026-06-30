"""Public read-only API v1 — for external consumption via API key.

Completely separate from the internal /api/* namespace: no require_admin,
no session cookies, GET-only. Auth is via X-API-Key (see
app.api.dependencies.require_api_key) checked against the api_keys table.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

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


@router.get("/simulations/{model_name}")
@limiter.limit(settings.RATE_LIMIT_PUBLIC_API)
def get_simulation(request: Request, model_name: str) -> dict[str, Any]:
    """Latest completed simulation results for a model.

    model_name: baseline | elo | poisson | poisson_context | ml_calibrated | consensus
    """
    if model_name not in _VALID_MODELS:
        raise HTTPException(status_code=400, detail=f"Invalid model_name. Must be one of: {sorted(_VALID_MODELS)}")

    with db_transaction() as conn:
        repo = SimulationRepository(conn)
        run = repo.get_latest_by_model(model_name)
        if not run:
            raise HTTPException(status_code=404, detail=f"No completed simulation for model '{model_name}'")
        return repo.get_run_summary(run["id"])


@router.get("/bracket/{model_name}")
@limiter.limit(settings.RATE_LIMIT_PUBLIC_API)
def get_bracket(request: Request, model_name: str) -> dict[str, Any]:
    """Live bracket probabilities (advance + next-match) for a model."""
    if model_name not in _VALID_MODELS:
        raise HTTPException(status_code=400, detail=f"Invalid model_name. Must be one of: {sorted(_VALID_MODELS)}")

    with db_transaction() as conn:
        rows = conn.execute(
            """
            SELECT bs.round_name, bs.team_id, t.name AS team_name,
                   bs.advance_prob, bs.opponent_id, o.name AS opponent_name,
                   bs.match_win_prob, bs.is_eliminated, bs.computed_at
            FROM bracket_simulations bs
            JOIN teams t ON t.id = bs.team_id
            LEFT JOIN teams o ON o.id = bs.opponent_id
            WHERE bs.model_name = ?
            ORDER BY bs.round_name, bs.advance_prob DESC
            """,
            (model_name,),
        ).fetchall()
        if not rows:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No bracket simulation found for model '{model_name}'. "
                    "El torneo puede no haber llegado aún a fase eliminatoria."
                ),
            )
        return {
            "model_name": model_name,
            "rounds":     [dict(r) for r in rows],
        }


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

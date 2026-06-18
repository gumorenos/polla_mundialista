"""Market odds endpoints — benchmark against The Odds API bookmaker data."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.dependencies import require_admin
from app.core.config import settings
from app.core.limiter import limiter
from app.db.connection import db_transaction
from app.db.repositories.odds import OddsRepository
from app.db.repositories.simulations import SimulationRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/odds", tags=["odds"])

_FAIR_THRESHOLD = 0.01  # |diff| < 1pp → "fair"


# ---------------------------------------------------------------------------
# GET /api/odds  — latest raw bookmaker odds
# ---------------------------------------------------------------------------

@router.get("")
@limiter.limit(settings.RATE_LIMIT_PUBLIC)
def get_odds(request: Request) -> dict[str, Any]:
    """Return latest bookmaker outright odds for all teams."""
    with db_transaction() as conn:
        repo = OddsRepository(conn)
        teams = repo.get_best_per_team()
        updated_at = repo.get_latest_fetch_time()

    return {"updated_at": updated_at, "teams": teams}


# ---------------------------------------------------------------------------
# GET /api/odds/value  — Oráculo vs. market comparison
# ---------------------------------------------------------------------------

@router.get("/value")
@limiter.limit(settings.RATE_LIMIT_PUBLIC)
def get_odds_value(
    request: Request,
    model: str = Query(default="ml_calibrated"),
) -> dict[str, Any]:
    """Compare simulation probabilities against bookmaker-implied probabilities."""
    with db_transaction() as conn:
        odds_repo = OddsRepository(conn)
        sim_repo  = SimulationRepository(conn)

        updated_at = odds_repo.get_latest_fetch_time()
        best_odds  = odds_repo.get_best_per_team()
        avg_probs  = odds_repo.get_avg_implied_prob_per_team()

        run = sim_repo.get_latest_by_model(model)
        if run is None:
            run = sim_repo.get_latest_by_model("poisson")
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No completed simulation found",
            )
        summary = sim_repo.get_run_summary(run["id"])

    # Build simulation lookup: team_id → win_tournament probability
    sim_map: dict[str, float] = {
        t["team_id"]: float(t["win_tournament"])
        for t in (summary.get("team_results") or [])
    }

    # Join best_odds with sim_map
    teams: list[dict[str, Any]] = []
    for odd in best_odds:
        team_id = odd["team_id"]
        oraculo_prob = sim_map.get(team_id)
        if oraculo_prob is None:
            continue
        market_prob = avg_probs.get(team_id, float(odd["implied_prob"]))
        value = round(oraculo_prob - market_prob, 6)

        if abs(value) < _FAIR_THRESHOLD:
            signal = "fair"
        elif value > 0:
            signal = "value"
        else:
            signal = "overpriced"

        teams.append({
            "team_id":      team_id,
            "team_name":    odd["team_name"],
            "oraculo_prob": round(oraculo_prob, 4),
            "market_prob":  round(market_prob, 4),
            "value":        value,
            "best_odd":     float(odd["decimal_odd"]),
            "bookmaker":    odd["bookmaker"],
            "signal":       signal,
        })

    # Sort by absolute value difference descending
    teams.sort(key=lambda t: abs(t["value"]), reverse=True)

    return {
        "model":      run.get("model_name", model),
        "updated_at": updated_at,
        "teams":      teams,
    }


# ---------------------------------------------------------------------------
# POST /api/odds/refresh  — admin trigger for manual refresh
# ---------------------------------------------------------------------------

@router.post("/refresh", dependencies=[Depends(require_admin)])
@limiter.limit(settings.RATE_LIMIT_ADMIN)
def trigger_odds_refresh(request: Request) -> dict[str, Any]:
    """Manually trigger a refresh of The Odds API data (admin only)."""
    from app.services.ingestion.odds_api import fetch_and_store_odds

    result = fetch_and_store_odds()
    return result

from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.db.connection import db_transaction
from app.db.repositories.elo_history import EloHistoryRepository

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("/{team_id}/elo-history")
def get_team_elo_history(team_id: str) -> list[dict]:
    with db_transaction() as conn:
        repo = EloHistoryRepository(conn)
        history = repo.get_team_history(team_id)
    if not history:
        raise HTTPException(status_code=404, detail="No ELO history found for this team")
    return history


@router.get("/{team_id}/statsbomb")
def get_team_statsbomb(team_id: str) -> dict[str, Any]:
    """Return aggregated StatsBomb stats for a team.

    Public endpoint — shows historical xG, possession, shot accuracy
    and other advanced metrics from WC 2018/2022 data.
    Returns 404 if the team has no StatsBomb records.
    """
    with db_transaction() as conn:
        team_row = conn.execute(
            "SELECT id, name FROM teams WHERE id = ?", (team_id,)
        ).fetchone()
        if not team_row:
            raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")

        row = conn.execute(
            """
            SELECT
                COUNT(*)                                        AS matches,
                ROUND(AVG(xg), 3)                               AS avg_xg,
                ROUND(AVG(xg_conceded), 3)                      AS avg_xg_conceded,
                ROUND(AVG(possession), 1)                       AS avg_possession,
                ROUND(
                    CASE WHEN SUM(shots) > 0
                         THEN 100.0 * SUM(shots_on_target) / SUM(shots)
                         ELSE NULL END, 1
                )                                               AS shot_accuracy_pct,
                ROUND(AVG(pressures), 1)                        AS avg_pressures,
                ROUND(
                    CASE WHEN SUM(duels_total) > 0
                         THEN 100.0 * SUM(duels_won) / SUM(duels_total)
                         ELSE NULL END, 1
                )                                               AS duel_win_rate_pct,
                ROUND(AVG(pass_accuracy), 1)                    AS avg_pass_accuracy,
                SUM(goals)                                      AS total_goals,
                ROUND(AVG(goals), 2)                            AS avg_goals
            FROM sb_match_stats
            WHERE team_id = ?
            """,
            (team_id,),
        ).fetchone()

        if not row or row["matches"] == 0:
            raise HTTPException(
                status_code=404,
                detail=f"No StatsBomb data found for team '{team_id}'",
            )

    return {
        "team_id":            team_id,
        "team_name":          team_row["name"],
        "matches":            row["matches"],
        "avg_xg":             row["avg_xg"],
        "avg_xg_conceded":    row["avg_xg_conceded"],
        "avg_possession":     row["avg_possession"],
        "shot_accuracy_pct":  row["shot_accuracy_pct"],
        "avg_pressures":      row["avg_pressures"],
        "duel_win_rate_pct":  row["duel_win_rate_pct"],
        "avg_pass_accuracy":  row["avg_pass_accuracy"],
        "total_goals":        row["total_goals"],
        "avg_goals":          row["avg_goals"],
    }


@router.get("/{team_id}/context")
def get_team_context(team_id: str) -> dict[str, Any]:
    """Return Poisson+Ctx contextual factors for a team: injuries, suspensions, altitude."""
    _MAX_INJ = 3  # mirrors _MAX_INJURY_PENALTY in poisson_context.py

    with db_transaction() as conn:
        team_row = conn.execute(
            "SELECT id, name FROM teams WHERE id = ?", (team_id,)
        ).fetchone()
        if not team_row:
            raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")

        # --- Injuries ---
        lookback = settings.NEWS_DAYS_LOOKBACK
        inj_rows = conn.execute(
            f"""
            SELECT player_name, status
            FROM availability_claims
            WHERE team_id = ?
              AND status IN ('injured', 'doubtful')
              AND affects_prediction = 1
              AND datetime(observed_at) >= datetime('now', '-{lookback} days')
            """,
            (team_id,),
        ).fetchall()
        inj_count = len(inj_rows)
        inj_capped = min(inj_count, _MAX_INJ)
        inj_penalty_pct = round(-(settings.INJURY_ATTACK_PENALTY * inj_capped) * 100, 1)

        # --- Suspensions ---
        yellow_rows = conn.execute(
            """
            SELECT player_name FROM (
                SELECT player_name FROM player_bookings
                WHERE team_id = ? AND competition = 'WC2026' AND card_type = 'YELLOW'
                GROUP BY player_name HAVING COUNT(*) >= 2
            )
            """,
            (team_id,),
        ).fetchall()
        red_rows = conn.execute(
            """
            SELECT DISTINCT player_name FROM player_bookings
            WHERE team_id = ? AND competition = 'WC2026' AND card_type IN ('RED', 'YELLOW_RED')
            """,
            (team_id,),
        ).fetchall()
        susp_count = len(yellow_rows) + len(red_rows)
        susp_capped = min(susp_count, _MAX_INJ)
        # compound formula: (1 - SUSPENSION_ATTACK_PENALTY)^n
        susp_factor = (1.0 - settings.SUSPENSION_ATTACK_PENALTY) ** susp_capped
        susp_penalty_pct = round((susp_factor - 1.0) * 100, 1)

        # --- Altitude venues ---
        altitude_entries: list[dict[str, Any]] = []
        try:
            from app.services.features.altitude_adjustment import get_altitude_adjustment
            venue_rows = conn.execute(
                """
                SELECT DISTINCT f.venue_id, v.name AS venue_name, v.altitude_m
                FROM fixtures f
                LEFT JOIN venues v ON v.id = f.venue_id
                WHERE f.venue_id IS NOT NULL
                  AND (f.home_team_id = ? OR f.away_team_id = ?)
                """,
                (team_id, team_id),
            ).fetchall()
            for vr in venue_rows:
                adj = get_altitude_adjustment(team_id, vr["venue_id"], conn)
                if adj and adj.get("combined", 1.0) != 1.0:
                    altitude_entries.append({
                        "venue_id":      vr["venue_id"],
                        "venue_name":    vr["venue_name"] or vr["venue_id"],
                        "altitude_m":    int(adj.get("altitude_m", 0)),
                        "adjustment_pct": round((adj["combined"] - 1.0) * 100, 1),
                    })
        except Exception:
            pass  # altitude data optional

        # --- xG availability ---
        xg_count = conn.execute(
            "SELECT COUNT(*) FROM sb_match_stats WHERE team_id = ?", (team_id,)
        ).fetchone()[0]

    return {
        "team_id":   team_id,
        "team_name": team_row["name"],
        "injuries": {
            "count":       inj_count,
            "penalty_pct": inj_penalty_pct,
            "players":     [r["player_name"] for r in inj_rows],
        },
        "suspensions": {
            "count":       susp_count,
            "penalty_pct": susp_penalty_pct,
        },
        "altitude_venues": altitude_entries,
        "xg_available":    xg_count > 0,
    }

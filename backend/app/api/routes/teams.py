from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

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

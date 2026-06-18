from __future__ import annotations

import sqlite3
import uuid
from typing import Any


class EloHistoryRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def clear_all(self) -> None:
        self._c.execute("DELETE FROM elo_history")

    def save_batch(self, entries: list[dict[str, Any]]) -> None:
        for e in entries:
            self._c.execute(
                """
                INSERT INTO elo_history
                    (id, team_id, elo_rating, match_date, opponent_id,
                     goals_for, goals_against, elo_change)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    e["team_id"],
                    float(e["elo_rating"]),
                    e["match_date"],
                    e.get("opponent_id"),
                    e.get("goals_for"),
                    e.get("goals_against"),
                    e.get("elo_change"),
                ),
            )

    # ------------------------------------------------------------------
    # Reads from elo_history
    # ------------------------------------------------------------------

    def get_team_history(self, team_id: str) -> list[dict[str, Any]]:
        """Return all ELO snapshots for *team_id*, joined with opponent name."""
        rows = self._c.execute(
            """
            SELECT eh.match_date, eh.elo_rating, eh.elo_change,
                   eh.opponent_id, t.name AS opponent_name,
                   eh.goals_for, eh.goals_against
            FROM elo_history eh
            LEFT JOIN teams t ON eh.opponent_id = t.id
            WHERE eh.team_id = ?
            ORDER BY eh.match_date, eh.rowid
            """,
            (team_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_match_date(self) -> str | None:
        """Return the latest match_date already processed into elo_history."""
        row = self._c.execute(
            "SELECT MAX(match_date) AS dt FROM elo_history"
        ).fetchone()
        return row["dt"] if row else None

    def count(self) -> int:
        row = self._c.execute("SELECT COUNT(*) AS n FROM elo_history").fetchone()
        return int(row["n"])

    # ------------------------------------------------------------------
    # Reads from results table (to drive ELO computation)
    # ------------------------------------------------------------------

    def get_all_results_ordered(self) -> list[dict[str, Any]]:
        """Return all results with known scores, oldest first."""
        rows = self._c.execute(
            """
            SELECT home_team_id, away_team_id,
                   home_goals, away_goals, match_date
            FROM results
            WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL
            ORDER BY match_date, id
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def get_results_since(self, date: str | None) -> list[dict[str, Any]]:
        """Return results with scores that happened strictly after *date*."""
        if date is None:
            return self.get_all_results_ordered()
        rows = self._c.execute(
            """
            SELECT home_team_id, away_team_id,
                   home_goals, away_goals, match_date
            FROM results
            WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL
              AND match_date > ?
            ORDER BY match_date, id
            """,
            (date,),
        ).fetchall()
        return [dict(r) for r in rows]

from __future__ import annotations

import sqlite3
import uuid
from typing import Any


class OddsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def replace_all(self, entries: list[dict[str, Any]]) -> None:
        """Replace all stored odds atomically with the latest fetch."""
        self._c.execute("DELETE FROM market_odds")
        for e in entries:
            self._c.execute(
                """
                INSERT INTO market_odds (id, team_id, bookmaker, decimal_odd, implied_prob)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    e["team_id"],
                    e["bookmaker"],
                    float(e["decimal_odd"]),
                    float(e["implied_prob"]),
                ),
            )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_team_name_map(self) -> dict[str, str]:
        """Return {lower_case_name: team_id} for all teams in DB."""
        rows = self._c.execute("SELECT id, name FROM teams").fetchall()
        return {r["name"].lower(): r["id"] for r in rows}

    def get_all(self) -> list[dict[str, Any]]:
        """Return all stored odds joined with team names."""
        rows = self._c.execute(
            """
            SELECT mo.team_id, t.name AS team_name,
                   mo.bookmaker, mo.decimal_odd, mo.implied_prob, mo.fetched_at
            FROM market_odds mo
            JOIN teams t ON mo.team_id = t.id
            ORDER BY mo.decimal_odd
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def get_best_per_team(self) -> list[dict[str, Any]]:
        """Return the highest decimal odd per team (best value for a bettor)."""
        rows = self._c.execute(
            """
            SELECT mo.team_id, t.name AS team_name,
                   mo.bookmaker, mo.decimal_odd, mo.implied_prob, mo.fetched_at
            FROM market_odds mo
            JOIN teams t ON mo.team_id = t.id
            WHERE mo.decimal_odd = (
                SELECT MAX(m2.decimal_odd)
                FROM market_odds m2
                WHERE m2.team_id = mo.team_id
            )
            GROUP BY mo.team_id
            ORDER BY mo.decimal_odd DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def get_avg_implied_prob_per_team(self) -> dict[str, float]:
        """Return {team_id: avg_implied_prob} averaged across all bookmakers."""
        rows = self._c.execute(
            """
            SELECT team_id, AVG(implied_prob) AS avg_prob
            FROM market_odds
            GROUP BY team_id
            """
        ).fetchall()
        return {r["team_id"]: float(r["avg_prob"]) for r in rows}

    def get_latest_fetch_time(self) -> str | None:
        row = self._c.execute(
            "SELECT MAX(fetched_at) AS ts FROM market_odds"
        ).fetchone()
        return row["ts"] if row else None

    def count(self) -> int:
        row = self._c.execute("SELECT COUNT(*) AS n FROM market_odds").fetchone()
        return int(row["n"])

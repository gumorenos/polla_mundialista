from __future__ import annotations

import sqlite3
import uuid
from typing import Any


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r else None


class StrengthRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def upsert(self, strength: dict[str, Any]) -> None:
        """Insert a new strength snapshot (append-only; never UPDATE)."""
        strength.setdefault("id", str(uuid.uuid4()))
        self._c.execute(
            """
            INSERT OR IGNORE INTO team_strengths
                (id, team_id, attack_strength, defense_vulnerability,
                 matches_used, cutoff_date, decay_factor)
            VALUES
                (:id, :team_id, :attack_strength, :defense_vulnerability,
                 :matches_used, :cutoff_date, :decay_factor)
            """,
            {
                "id":                   strength["id"],
                "team_id":              strength["team_id"],
                "attack_strength":      strength["attack_strength"],
                "defense_vulnerability": strength["defense_vulnerability"],
                "matches_used":         strength.get("matches_used"),
                "cutoff_date":          strength.get("cutoff_date"),
                "decay_factor":         strength.get("decay_factor"),
            },
        )

    def get_by_team(self, team_id: str) -> dict[str, Any] | None:
        """Return the most recently computed strength for a team."""
        return _row(
            self._c.execute(
                """
                SELECT * FROM team_strengths
                WHERE team_id = ?
                ORDER BY computed_at DESC
                LIMIT 1
                """,
                (team_id,),
            ).fetchone()
        )

    def get_all(self) -> list[dict[str, Any]]:
        """Return the latest strength snapshot per team."""
        rows = self._c.execute(
            """
            SELECT s.* FROM team_strengths s
            INNER JOIN (
                SELECT team_id, MAX(computed_at) AS max_at
                FROM team_strengths
                GROUP BY team_id
            ) latest ON s.team_id = latest.team_id
                     AND s.computed_at = latest.max_at
            ORDER BY s.attack_strength DESC
            """,
        ).fetchall()
        return [dict(r) for r in rows]

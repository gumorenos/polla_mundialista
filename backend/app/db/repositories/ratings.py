from __future__ import annotations

import sqlite3
import uuid
from typing import Any


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r else None


class RatingRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def upsert_elo(self, team_id: str, value: float, effective_date: str, source: str = "elo") -> None:
        self._upsert(team_id, "elo", value, None, effective_date, source)

    def upsert_fifa(
        self,
        team_id: str,
        value: float,
        rank: int,
        effective_date: str,
        source: str = "fifa",
    ) -> None:
        self._upsert(team_id, "fifa", value, rank, effective_date, source)

    def get_latest(self, team_id: str, rating_type: str) -> dict[str, Any] | None:
        return _row(
            self._c.execute(
                """
                SELECT * FROM ratings
                WHERE team_id = ? AND rating_type = ?
                ORDER BY effective_date DESC
                LIMIT 1
                """,
                (team_id, rating_type),
            ).fetchone()
        )

    def list_latest_excluding_source(
        self, rating_type: str, exclude_source: str
    ) -> list[dict[str, Any]]:
        """Latest rating per team excluding rows with *exclude_source*.

        Prevents our own computed ELOs from drifting when used as their own baseline.
        """
        rows = self._c.execute(
            """
            SELECT r.team_id, r.value, r.effective_date, r.source
            FROM ratings r
            INNER JOIN (
                SELECT team_id, MAX(effective_date) AS max_date
                FROM ratings
                WHERE rating_type = ? AND source != ?
                GROUP BY team_id
            ) latest ON r.team_id = latest.team_id
                     AND r.effective_date = latest.max_date
                     AND r.rating_type = ?
                     AND r.source != ?
            ORDER BY r.value DESC
            """,
            (rating_type, exclude_source, rating_type, exclude_source),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_latest_all(self, rating_type: str) -> list[dict[str, Any]]:
        """Return the most recent rating of *rating_type* for every team."""
        rows = self._c.execute(
            """
            SELECT r.* FROM ratings r
            INNER JOIN (
                SELECT team_id, MAX(effective_date) AS max_date
                FROM ratings WHERE rating_type = ?
                GROUP BY team_id
            ) latest ON r.team_id = latest.team_id
                     AND r.effective_date = latest.max_date
                     AND r.rating_type = ?
            ORDER BY r.value DESC
            """,
            (rating_type, rating_type),
        ).fetchall()
        return [dict(r) for r in rows]

    def _upsert(
        self,
        team_id: str,
        rating_type: str,
        value: float,
        rank: int | None,
        effective_date: str,
        source: str,
    ) -> None:
        self._c.execute(
            """
            INSERT INTO ratings (id, team_id, rating_type, value, rank, effective_date, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(team_id, rating_type, source)
            DO UPDATE SET
                value          = excluded.value,
                rank           = excluded.rank,
                effective_date = excluded.effective_date
            """,
            (str(uuid.uuid4()), team_id, rating_type, value, rank, effective_date, source),
        )

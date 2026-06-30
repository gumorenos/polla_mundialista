from __future__ import annotations

import sqlite3


class BracketRepository:
    """Persistence for the live bracket simulator results."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def upsert_many(self, rows: list[tuple]) -> None:
        """Bulk upsert (model_name, round_name, team_id, advance_prob,
        opponent_id, match_win_prob, is_eliminated) rows."""
        self._c.executemany(
            """
            INSERT INTO bracket_simulations
                (model_name, round_name, team_id, advance_prob,
                 opponent_id, match_win_prob, is_eliminated, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(model_name, round_name, team_id) DO UPDATE SET
                advance_prob   = excluded.advance_prob,
                opponent_id    = excluded.opponent_id,
                match_win_prob = excluded.match_win_prob,
                is_eliminated  = excluded.is_eliminated,
                computed_at    = excluded.computed_at
            """,
            rows,
        )

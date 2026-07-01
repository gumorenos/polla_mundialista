from __future__ import annotations

import secrets
import sqlite3
from typing import Any


class BracketRepository:
    """Persistence for the live bracket simulator — historical runs
    (bracket_runs + bracket_simulation_results) plus the legacy
    latest-only cache (bracket_simulations, kept for backward compat)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    # ------------------------------------------------------------------
    # Legacy latest-only cache (superseded by bracket_runs history below,
    # kept only so the table isn't left dangling — no longer written to
    # by run_bracket_simulation).
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # bracket_runs — one row per simulation attempt, historical
    # ------------------------------------------------------------------

    def create_run(self, model_name: str, iterations: int, source: str = "manual") -> str:
        run_id = secrets.token_hex(8)
        self._c.execute(
            """
            INSERT INTO bracket_runs (id, model_name, status, iterations, source, started_at)
            VALUES (?, ?, 'running', ?, ?, datetime('now'))
            """,
            (run_id, model_name, iterations, source),
        )
        return run_id

    def finish_run(
        self,
        run_id: str,
        status: str,
        error_message: str | None = None,
        r32_source: str | None = None,
        r32_fetched_at: str | None = None,
    ) -> None:
        self._c.execute(
            """
            UPDATE bracket_runs
            SET status = ?, error_message = ?, r32_source = ?, r32_fetched_at = ?,
                finished_at = datetime('now')
            WHERE id = ?
            """,
            (status, error_message, r32_source, r32_fetched_at, run_id),
        )

    def insert_results(self, rows: list[tuple]) -> None:
        """rows: (bracket_run_id, model_name, round_name, team_id, advance_prob,
        opponent_id, match_win_prob, is_eliminated)."""
        if not rows:
            return
        self._c.executemany(
            """
            INSERT INTO bracket_simulation_results
                (bracket_run_id, model_name, round_name, team_id, advance_prob,
                 opponent_id, match_win_prob, is_eliminated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._c.execute("SELECT * FROM bracket_runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def get_latest_completed_run(self, model_name: str) -> dict[str, Any] | None:
        row = self._c.execute(
            """
            SELECT * FROM bracket_runs
            WHERE model_name = ? AND status = 'completed'
            ORDER BY finished_at DESC LIMIT 1
            """,
            (model_name,),
        ).fetchone()
        return dict(row) if row else None

    def get_latest_run(self, model_name: str) -> dict[str, Any] | None:
        """Latest run regardless of status — used to surface a fresh 'no_r32'
        message even when there has never been a completed run."""
        row = self._c.execute(
            "SELECT * FROM bracket_runs WHERE model_name = ? ORDER BY created_at DESC LIMIT 1",
            (model_name,),
        ).fetchone()
        return dict(row) if row else None

    def list_runs(self, model_name: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._c.execute(
            """
            SELECT id, model_name, status, iterations, source, r32_source,
                   r32_fetched_at, started_at, finished_at, error_message, created_at
            FROM bracket_runs
            WHERE model_name = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (model_name, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_run_results(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._c.execute(
            """
            SELECT bsr.round_name, bsr.team_id, t.name AS team_name, bsr.advance_prob,
                   bsr.opponent_id, o.name AS opponent_name, bsr.match_win_prob,
                   bsr.is_eliminated, bsr.computed_at
            FROM bracket_simulation_results bsr
            JOIN teams t ON t.id = bsr.team_id
            LEFT JOIN teams o ON o.id = bsr.opponent_id
            WHERE bsr.bracket_run_id = ?
            ORDER BY bsr.round_name, bsr.advance_prob DESC
            """,
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

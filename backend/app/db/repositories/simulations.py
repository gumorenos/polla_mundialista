from __future__ import annotations

import sqlite3
import uuid
from typing import Any


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r else None


class SimulationRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    # ------------------------------------------------------------------
    # Simulation runs
    # ------------------------------------------------------------------

    def create_run(self, run: dict[str, Any]) -> str:
        run_id = run.get("id") or str(uuid.uuid4())
        self._c.execute(
            """
            INSERT INTO simulation_runs
                (id, prediction_run_id, model_name, status,
                 iterations, seed, data_version_hash, config_snapshot)
            VALUES
                (:id, :prediction_run_id, :model_name, :status,
                 :iterations, :seed, :data_version_hash, :config_snapshot)
            """,
            {
                "id":                 run_id,
                "prediction_run_id":  run.get("prediction_run_id"),
                "model_name":         run["model_name"],
                "status":             run.get("status", "pending"),
                "iterations":         run.get("iterations", 30_000),
                "seed":               run.get("seed", 42),
                "data_version_hash":  run.get("data_version_hash"),
                "config_snapshot":    run.get("config_snapshot"),
            },
        )
        return run_id

    def update_run_status(
        self,
        run_id: str,
        status: str,
        started_at: str | None = None,
        finished_at: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self._c.execute(
            """
            UPDATE simulation_runs
            SET status        = ?,
                started_at    = COALESCE(?, started_at),
                finished_at   = COALESCE(?, finished_at),
                error_message = COALESCE(?, error_message)
            WHERE id = ?
            """,
            (status, started_at, finished_at, error_message, run_id),
        )

    def get_latest_by_model(self, model_name: str) -> dict[str, Any] | None:
        return _row(
            self._c.execute(
                """
                SELECT sr.* FROM simulation_runs sr
                WHERE sr.model_name = ?
                  AND sr.status = 'completed'
                  AND EXISTS (
                      SELECT 1 FROM simulation_team_results str
                      WHERE str.simulation_run_id = sr.id
                  )
                ORDER BY sr.finished_at DESC
                LIMIT 1
                """,
                (model_name,),
            ).fetchone()
        )

    # ------------------------------------------------------------------
    # Team results (INSERT only — no UPDATE)
    # ------------------------------------------------------------------

    def insert_team_result(self, result: dict[str, Any]) -> str:
        result_id = result.get("id") or str(uuid.uuid4())
        self._c.execute(
            """
            INSERT OR IGNORE INTO simulation_team_results
                (id, simulation_run_id, team_id,
                 win_group, qualify,
                 reach_round_of_32, reach_round_of_16,
                 reach_quarter_final, reach_semi_final,
                 reach_final, win_tournament, expected_group_points)
            VALUES
                (:id, :simulation_run_id, :team_id,
                 :win_group, :qualify,
                 :reach_round_of_32, :reach_round_of_16,
                 :reach_quarter_final, :reach_semi_final,
                 :reach_final, :win_tournament, :expected_group_points)
            """,
            {
                "id":                   result_id,
                "simulation_run_id":    result["simulation_run_id"],
                "team_id":              result.get("team_id"),
                "win_group":            result.get("win_group"),
                "qualify":              result.get("qualify"),
                "reach_round_of_32":    result.get("reach_round_of_32"),
                "reach_round_of_16":    result.get("reach_round_of_16"),
                "reach_quarter_final":  result.get("reach_quarter_final"),
                "reach_semi_final":     result.get("reach_semi_final"),
                "reach_final":          result.get("reach_final"),
                "win_tournament":       result.get("win_tournament"),
                "expected_group_points": result.get("expected_group_points"),
            },
        )
        return result_id

    def create_snapshot(self, snap: dict[str, Any]) -> str:
        """Persist a snapshot record linked to a simulation run."""
        import uuid
        snap_id = snap.get("id") or str(uuid.uuid4())
        self._c.execute(
            """
            INSERT INTO snapshots
                (id, label, description, trigger, simulation_run_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                snap_id,
                snap.get("label"),
                snap.get("description"),
                snap.get("trigger"),
                snap.get("simulation_run_id"),
            ),
        )
        return snap_id

    def get_snapshot_by_id(self, snapshot_id: str) -> dict[str, Any] | None:
        return _row(
            self._c.execute(
                "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
        )

    def list_snapshots(self, limit: int = 50) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self._c.execute(
                "SELECT * FROM snapshots ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        ]

    def get_run_summary(self, simulation_run_id: str) -> dict[str, Any]:
        run = _row(
            self._c.execute(
                "SELECT * FROM simulation_runs WHERE id = ?", (simulation_run_id,)
            ).fetchone()
        )
        if not run:
            return {}
        rows = self._c.execute(
            """
            SELECT str.*, t.name AS team_name
            FROM simulation_team_results str
            LEFT JOIN teams t ON str.team_id = t.id
            WHERE str.simulation_run_id = ?
            ORDER BY str.win_tournament DESC
            """,
            (simulation_run_id,),
        ).fetchall()
        return {"run": run, "team_results": [dict(r) for r in rows]}

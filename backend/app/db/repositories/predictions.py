from __future__ import annotations

import sqlite3
import uuid
from typing import Any


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r else None


class PredictionRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    # ------------------------------------------------------------------
    # Prediction runs
    # ------------------------------------------------------------------

    def create_run(self, run: dict[str, Any]) -> str:
        run_id = run.get("id") or str(uuid.uuid4())
        self._c.execute(
            """
            INSERT INTO prediction_runs
                (id, model_set, status, data_version_hash, config_snapshot)
            VALUES (:id, :model_set, :status, :data_version_hash, :config_snapshot)
            """,
            {
                "id":                run_id,
                "model_set":         run.get("model_set"),
                "status":            run.get("status", "pending"),
                "data_version_hash": run.get("data_version_hash"),
                "config_snapshot":   run.get("config_snapshot"),
            },
        )
        return run_id

    def update_run_status(
        self,
        run_id: str,
        status: str,
        finished_at: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self._c.execute(
            """
            UPDATE prediction_runs
            SET status        = ?,
                finished_at   = COALESCE(?, finished_at),
                error_message = COALESCE(?, error_message)
            WHERE id = ?
            """,
            (status, finished_at, error_message, run_id),
        )

    def get_latest_run(self) -> dict[str, Any] | None:
        return _row(
            self._c.execute(
                "SELECT * FROM prediction_runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        )

    # ------------------------------------------------------------------
    # Match predictions (INSERT only — no UPDATE)
    # ------------------------------------------------------------------

    def insert_prediction(self, prediction: dict[str, Any]) -> str:
        pred_id = prediction.get("id") or str(uuid.uuid4())
        self._c.execute(
            """
            INSERT OR IGNORE INTO match_predictions
                (id, run_id, fixture_id, model_name, model_version,
                 home_win, draw, away_win,
                 expected_home_goals, expected_away_goals,
                 most_likely_score, features_used, features_missing, explanation)
            VALUES
                (:id, :run_id, :fixture_id, :model_name, :model_version,
                 :home_win, :draw, :away_win,
                 :expected_home_goals, :expected_away_goals,
                 :most_likely_score, :features_used, :features_missing, :explanation)
            """,
            {
                "id":                   pred_id,
                "run_id":               prediction["run_id"],
                "fixture_id":           prediction.get("fixture_id"),
                "model_name":           prediction["model_name"],
                "model_version":        prediction.get("model_version"),
                "home_win":             prediction.get("home_win"),
                "draw":                 prediction.get("draw"),
                "away_win":             prediction.get("away_win"),
                "expected_home_goals":  prediction.get("expected_home_goals"),
                "expected_away_goals":  prediction.get("expected_away_goals"),
                "most_likely_score":    prediction.get("most_likely_score"),
                "features_used":        prediction.get("features_used"),
                "features_missing":     prediction.get("features_missing"),
                "explanation":          prediction.get("explanation"),
            },
        )
        return pred_id

    def get_by_model(
        self, model_name: str, run_id: str | None = None
    ) -> list[dict[str, Any]]:
        if run_id:
            rows = self._c.execute(
                """
                SELECT * FROM match_predictions
                WHERE model_name = ? AND run_id = ?
                ORDER BY created_at DESC
                """,
                (model_name, run_id),
            ).fetchall()
        else:
            rows = self._c.execute(
                """
                SELECT * FROM match_predictions
                WHERE model_name = ?
                ORDER BY created_at DESC
                """,
                (model_name,),
            ).fetchall()
        return [dict(r) for r in rows]

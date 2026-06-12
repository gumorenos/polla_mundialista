from __future__ import annotations

import sqlite3
import uuid
from typing import Any


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r else None


class MLRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def create_training_run(self, run: dict[str, Any]) -> str:
        run_id = run.get("id") or str(uuid.uuid4())
        self._c.execute(
            """
            INSERT OR IGNORE INTO ml_training_runs
                (id, algorithm, train_start_year, train_end_date,
                 validation_split, feature_set, hyperparams, status)
            VALUES
                (:id, :algorithm, :train_start_year, :train_end_date,
                 :validation_split, :feature_set, :hyperparams, :status)
            """,
            {
                "id":               run_id,
                "algorithm":        run["algorithm"],
                "train_start_year": run.get("train_start_year"),
                "train_end_date":   run.get("train_end_date"),
                "validation_split": run.get("validation_split"),
                "feature_set":      run.get("feature_set"),
                "hyperparams":      run.get("hyperparams"),
                "status":           run.get("status", "pending"),
            },
        )
        return run_id

    def save_model_path(
        self,
        training_run_id: str,
        algorithm: str,
        model_path: str,
        metrics: dict[str, float] | None = None,
    ) -> str:
        model_id = str(uuid.uuid4())
        m = metrics or {}
        self._c.execute(
            """
            INSERT OR IGNORE INTO ml_models
                (id, training_run_id, algorithm, model_path,
                 brier_score, log_loss, accuracy)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model_id, training_run_id, algorithm, model_path,
                m.get("brier_score"), m.get("log_loss"), m.get("accuracy"),
            ),
        )
        return model_id

    def get_best_model(self) -> dict[str, Any] | None:
        """Return the active model with the lowest Brier score."""
        return _row(
            self._c.execute(
                """
                SELECT * FROM ml_models
                WHERE is_active = 1
                ORDER BY brier_score ASC
                LIMIT 1
                """
            ).fetchone()
        )

    def set_active_model(self, model_id: str) -> None:
        """Mark one model as active and deactivate all others."""
        self._c.execute("UPDATE ml_models SET is_active = 0")
        self._c.execute(
            "UPDATE ml_models SET is_active = 1 WHERE id = ?", (model_id,)
        )

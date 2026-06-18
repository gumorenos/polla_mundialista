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

    def update_training_run(
        self,
        run_id: str,
        status: str,
        started_at: str | None = None,
        finished_at: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update status and optional timestamps / error on a training run."""
        self._c.execute(
            """
            UPDATE ml_training_runs
               SET status        = ?,
                   started_at    = COALESCE(?, started_at),
                   finished_at   = COALESCE(?, finished_at),
                   error_message = COALESCE(?, error_message)
             WHERE id = ?
            """,
            (status, started_at, finished_at, error_message, run_id),
        )

    def save_feature_snapshot(
        self,
        training_run_id: str,
        feature_names: list[str],
        feature_importances: list[float] | None,
    ) -> str:
        snapshot_id = str(uuid.uuid4())
        import json
        self._c.execute(
            """
            INSERT INTO ml_feature_snapshots
                (id, training_run_id, feature_names, feature_importances)
            VALUES (?, ?, ?, ?)
            """,
            (
                snapshot_id, training_run_id,
                json.dumps(feature_names),
                json.dumps(feature_importances) if feature_importances else None,
            ),
        )
        return snapshot_id

    def list_models(self) -> list[dict[str, Any]]:
        """Return all trained ML models ordered by Brier score then recency."""
        rows = self._c.execute(
            """
            SELECT m.id, m.training_run_id, m.algorithm, m.model_path,
                   m.brier_score, m.log_loss, m.accuracy, m.is_active,
                   m.created_at,
                   r.train_start_year, r.validation_split,
                   r.status AS run_status
              FROM ml_models m
         LEFT JOIN ml_training_runs r ON m.training_run_id = r.id
             ORDER BY m.brier_score ASC, m.created_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def save_shap_importance(self, model_id: str, shap_json: str) -> None:
        """Persist SHAP global importance JSON on a model record."""
        self._c.execute(
            "UPDATE ml_models SET shap_importance = ? WHERE id = ?",
            (shap_json, model_id),
        )

    def get_active_shap_importance(self) -> dict[str, Any] | None:
        """Return (model_id, algorithm, shap_importance) for the active model."""
        return _row(
            self._c.execute(
                """
                SELECT id, algorithm, shap_importance
                FROM ml_models
                WHERE is_active = 1
                ORDER BY brier_score ASC
                LIMIT 1
                """
            ).fetchone()
        )

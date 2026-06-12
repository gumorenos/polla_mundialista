from __future__ import annotations

import sqlite3
import uuid
from typing import Any


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r else None


class EvaluationRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def insert_evaluation(self, evaluation: dict[str, Any]) -> str:
        eval_id = evaluation.get("id") or str(uuid.uuid4())
        self._c.execute(
            """
            INSERT OR IGNORE INTO model_evaluations
                (id, model_name, model_version, eval_set, n_matches,
                 brier_score, log_loss, rps, accuracy, calibration_error)
            VALUES
                (:id, :model_name, :model_version, :eval_set, :n_matches,
                 :brier_score, :log_loss, :rps, :accuracy, :calibration_error)
            """,
            {
                "id":                eval_id,
                "model_name":        evaluation["model_name"],
                "model_version":     evaluation.get("model_version"),
                "eval_set":          evaluation.get("eval_set"),
                "n_matches":         evaluation.get("n_matches"),
                "brier_score":       evaluation.get("brier_score"),
                "log_loss":          evaluation.get("log_loss"),
                "rps":               evaluation.get("rps"),
                "accuracy":          evaluation.get("accuracy"),
                "calibration_error": evaluation.get("calibration_error"),
            },
        )
        return eval_id

    def get_by_model(self, model_name: str) -> list[dict[str, Any]]:
        rows = self._c.execute(
            """
            SELECT * FROM model_evaluations
            WHERE model_name = ?
            ORDER BY evaluated_at DESC
            """,
            (model_name,),
        ).fetchall()
        return [dict(r) for r in rows]

    def compute_aggregate_metrics(self, model_name: str) -> dict[str, Any]:
        """Return AVG of each metric across all evaluations for a model."""
        row = self._c.execute(
            """
            SELECT
                model_name,
                COUNT(*)              AS n_evaluations,
                AVG(brier_score)      AS avg_brier,
                AVG(log_loss)         AS avg_log_loss,
                AVG(rps)              AS avg_rps,
                AVG(accuracy)         AS avg_accuracy,
                AVG(calibration_error) AS avg_calibration_error
            FROM model_evaluations
            WHERE model_name = ?
            GROUP BY model_name
            """,
            (model_name,),
        ).fetchone()
        return dict(row) if row else {}

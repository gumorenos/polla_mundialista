"""AdminRepository — privileged DB operations for the reset endpoint."""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

# Tables wiped during a full reset (StatsBomb and reference tables are excluded)
_RESET_TABLES = [
    "simulation_team_results",
    "simulation_runs",
    "match_predictions",
    "prediction_runs",
    "snapshots",
    "model_evaluations",
    "ml_feature_snapshots",
    "ml_models",
    "ml_training_runs",
    "narrative_cache",
    "elo_history",
    "team_context_adjustments",
    "availability_claims",
    "team_strengths",
]


class AdminRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def reset_transient_data(self) -> dict[str, int]:
        """Delete all rows from transient tables, leaving reference and StatsBomb data intact.

        Returns a dict mapping table name → rows deleted (-1 on error).
        """
        deleted: dict[str, int] = {}
        for table in _RESET_TABLES:
            try:
                cur = self._c.execute(f"DELETE FROM {table}")  # noqa: S608 — table list is hardcoded
                deleted[table] = cur.rowcount
            except Exception as exc:
                logger.warning("reset_transient_data: could not truncate %s: %s", table, exc)
                deleted[table] = -1

        # Completed/terminal jobs only
        try:
            cur = self._c.execute(
                "DELETE FROM jobs WHERE status IN ('completed', 'failed', 'cancelled')"
            )
            deleted["jobs(terminal)"] = cur.rowcount
        except Exception as exc:
            logger.warning("reset_transient_data: could not clean jobs: %s", exc)
            deleted["jobs(terminal)"] = -1

        return deleted

    def vacuum(self) -> None:
        """Run VACUUM to reclaim space after bulk deletes."""
        try:
            self._c.execute("VACUUM")
        except Exception as exc:
            logger.warning("AdminRepository.vacuum failed: %s", exc)

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any


class NarrativeRepository:
    _CACHE_TTL_HOURS = 6

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def get_cached(
        self,
        run_id: str,
        model_name: str,
        team_id: str | None,
    ) -> str | None:
        """Return a cached narrative if still fresh (< 6 h), else None."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=self._CACHE_TTL_HOURS)
        ).isoformat()
        row = self._c.execute(
            """
            SELECT narrative FROM narrative_cache
            WHERE run_id = ? AND model_name = ? AND team_id IS ?
              AND generated_at > ?
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (run_id, model_name, team_id, cutoff),
        ).fetchone()
        return row[0] if row else None

    def save(
        self,
        run_id: str,
        model_name: str,
        narrative: str,
        team_id: str | None = None,
    ) -> None:
        """Upsert a narrative into the cache (replace stale entries)."""
        self._c.execute(
            """
            DELETE FROM narrative_cache
            WHERE run_id = ? AND model_name = ? AND team_id IS ?
            """,
            (run_id, model_name, team_id),
        )
        self._c.execute(
            """
            INSERT INTO narrative_cache (id, run_id, team_id, model_name, narrative)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), run_id, team_id, model_name, narrative),
        )

    def get_with_meta(
        self,
        run_id: str,
        model_name: str,
        team_id: str | None,
    ) -> dict[str, Any] | None:
        """Return {narrative, generated_at} regardless of age, for display."""
        row = self._c.execute(
            """
            SELECT narrative, generated_at FROM narrative_cache
            WHERE run_id = ? AND model_name = ? AND team_id IS ?
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (run_id, model_name, team_id),
        ).fetchone()
        return {"narrative": row[0], "generated_at": row[1]} if row else None

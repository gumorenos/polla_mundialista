from __future__ import annotations

import sqlite3
import uuid
from typing import Any


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r else None


class AvailabilityRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def insert_claim(self, claim: dict[str, Any]) -> str:
        """Insert a new availability claim and return its id."""
        claim_id = claim.get("id") or str(uuid.uuid4())
        self._c.execute(
            """
            INSERT OR IGNORE INTO availability_claims
                (id, team_id, player_name, player_key, status, reason,
                 source_url, source_name, confidence, evidence_level,
                 observed_at, published_at, affects_prediction, raw_json)
            VALUES
                (:id, :team_id, :player_name, :player_key, :status, :reason,
                 :source_url, :source_name, :confidence, :evidence_level,
                 :observed_at, :published_at, :affects_prediction, :raw_json)
            """,
            {
                "id":                 claim_id,
                "team_id":            claim.get("team_id"),
                "player_name":        claim["player_name"],
                "player_key":         claim.get("player_key"),
                "status":             claim["status"],
                "reason":             claim.get("reason"),
                "source_url":         claim.get("source_url"),
                "source_name":        claim.get("source_name"),
                "confidence":         claim.get("confidence"),
                "evidence_level":     claim.get("evidence_level"),
                "observed_at":        claim["observed_at"],
                "published_at":       claim.get("published_at"),
                "affects_prediction": int(claim.get("affects_prediction", False)),
                "raw_json":           claim.get("raw_json"),
            },
        )
        return claim_id

    def get_active_by_team(
        self, team_id: str, days_lookback: int = 7
    ) -> list[dict[str, Any]]:
        """Return claims for a team observed within *days_lookback* days."""
        rows = self._c.execute(
            """
            SELECT * FROM availability_claims
            WHERE team_id = ?
              AND datetime(observed_at) >= datetime('now', ?)
            ORDER BY observed_at DESC
            """,
            (team_id, f"-{days_lookback} days"),
        ).fetchall()
        return [dict(r) for r in rows]

    def insert_context_adjustment(
        self,
        team_id: str,
        attack_factor: float,
        defense_factor: float,
        notes: str,
        adjustment_type: str = "injury",
    ) -> str:
        """Persist an injury-based context adjustment for a team."""
        adj_id = str(uuid.uuid4())
        self._c.execute(
            """
            INSERT INTO team_context_adjustments
                (id, team_id, adjustment_type, attack_factor, defense_factor, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (adj_id, team_id, adjustment_type, attack_factor, defense_factor, notes),
        )
        return adj_id

    def expire_stale_claims(self, days_lookback: int) -> None:
        """Mark claims older than *days_lookback* days as 'available'."""
        self._c.execute(
            """
            UPDATE availability_claims
               SET status = 'available'
             WHERE observed_at < datetime('now', ?)
               AND status NOT IN ('available', 'unknown')
            """,
            (f"-{days_lookback} days",),
        )

    def delete_claim(self, claim_id: str) -> int:
        """Delete a single availability claim by ID. Returns rows deleted (0 or 1)."""
        cur = self._c.execute(
            "DELETE FROM availability_claims WHERE id = ?",
            (claim_id,),
        )
        return cur.rowcount

    def purge_old_claims(self, days: int = 7) -> int:
        """Hard-delete availability_claims older than *days* days. Returns count deleted."""
        cur = self._c.execute(
            "DELETE FROM availability_claims WHERE observed_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        return cur.rowcount

    def get_by_player(self, player_key: str) -> list[dict[str, Any]]:
        rows = self._c.execute(
            """
            SELECT * FROM availability_claims
            WHERE player_key = ?
            ORDER BY observed_at DESC
            """,
            (player_key,),
        ).fetchall()
        return [dict(r) for r in rows]

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
                 observed_at, affects_prediction, raw_json)
            VALUES
                (:id, :team_id, :player_name, :player_key, :status, :reason,
                 :source_url, :source_name, :confidence, :evidence_level,
                 :observed_at, :affects_prediction, :raw_json)
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

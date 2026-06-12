from __future__ import annotations

import sqlite3
import uuid
from typing import Any


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r else None


class TeamRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def get_by_id(self, team_id: str) -> dict[str, Any] | None:
        return _row(
            self._c.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
        )

    def get_by_name(self, name: str) -> dict[str, Any] | None:
        return _row(
            self._c.execute(
                "SELECT * FROM teams WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
        )

    def upsert(self, team: dict[str, Any]) -> None:
        team.setdefault("id", str(uuid.uuid4()))
        self._c.execute(
            """
            INSERT INTO teams (id, name, code, confederation, is_host)
            VALUES (:id, :name, :code, :confederation, :is_host)
            ON CONFLICT(id) DO UPDATE SET
                name          = excluded.name,
                code          = excluded.code,
                confederation = excluded.confederation,
                is_host       = excluded.is_host,
                updated_at    = strftime('%Y-%m-%dT%H:%M:%SZ','now')
            """,
            {
                "id": team.get("id"),
                "name": team["name"],
                "code": team.get("code"),
                "confederation": team.get("confederation"),
                "is_host": int(team.get("is_host", False)),
            },
        )

    def list_all(self) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self._c.execute(
                "SELECT * FROM teams ORDER BY name"
            ).fetchall()
        ]

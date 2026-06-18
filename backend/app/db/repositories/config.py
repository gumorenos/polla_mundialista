from __future__ import annotations

import sqlite3
from typing import Any


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r else None


class ConfigRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def list_all(self) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self._c.execute(
                "SELECT key, value, description, updated_at FROM app_config ORDER BY key"
            ).fetchall()
        ]

    def get_value(self, key: str) -> str | None:
        row = self._c.execute(
            "SELECT value FROM app_config WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def set_value(self, key: str, value: str) -> dict[str, Any] | None:
        cur = self._c.execute(
            "UPDATE app_config SET value = ?, updated_at = datetime('now') WHERE key = ?",
            (value, key),
        )
        if cur.rowcount == 0:
            return None
        return _row(
            self._c.execute(
                "SELECT key, value, description, updated_at FROM app_config WHERE key = ?",
                (key,),
            ).fetchone()
        )

    def reset_all(self, defaults: dict[str, tuple[str, str]]) -> list[dict[str, Any]]:
        for key, (value, _) in defaults.items():
            self._c.execute(
                "UPDATE app_config SET value = ?, updated_at = datetime('now') WHERE key = ?",
                (value, key),
            )
        return self.list_all()

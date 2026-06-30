from __future__ import annotations

import sqlite3
from typing import Any


class ApiKeyRepository:
    """Lookup/maintenance for the public-API key store."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def get_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        row = self._c.execute(
            "SELECT id, label, revoked FROM api_keys WHERE key_hash = ?",
            (key_hash,),
        ).fetchone()
        return dict(row) if row else None

    def touch_last_used(self, key_id: str) -> None:
        self._c.execute(
            "UPDATE api_keys SET last_used_at = datetime('now') WHERE id = ?",
            (key_id,),
        )

    def create(self, key_hash: str, label: str) -> str:
        self._c.execute(
            "INSERT INTO api_keys (key_hash, label) VALUES (?, ?)",
            (key_hash, label),
        )
        row = self._c.execute(
            "SELECT id FROM api_keys WHERE key_hash = ?", (key_hash,)
        ).fetchone()
        return row["id"]

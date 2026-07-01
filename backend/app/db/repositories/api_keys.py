from __future__ import annotations

import secrets
import sqlite3
from typing import Any


class ApiKeyRepository:
    """Lookup/maintenance for the public-API key store.

    The raw key is never persisted — only its SHA-256 hash and a short
    prefix (for display in admin listings, e.g. "om26_ab12cd34...")."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def get_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        row = self._c.execute(
            "SELECT id, label, revoked, rate_limit_per_minute, scopes FROM api_keys WHERE key_hash = ?",
            (key_hash,),
        ).fetchone()
        return dict(row) if row else None

    def touch_last_used(self, key_id: str) -> None:
        self._c.execute(
            "UPDATE api_keys SET last_used_at = datetime('now') WHERE id = ?",
            (key_id,),
        )

    def create(self, key_hash: str, label: str) -> str:
        """Legacy creation path (used by the original create_api_key.py script
        before prefix/scopes existed). Prefer create_with_prefix for new code."""
        self._c.execute(
            "INSERT INTO api_keys (key_hash, label) VALUES (?, ?)",
            (key_hash, label),
        )
        row = self._c.execute(
            "SELECT id FROM api_keys WHERE key_hash = ?", (key_hash,)
        ).fetchone()
        return row["id"]

    def create_with_prefix(
        self,
        key_hash: str,
        prefix: str,
        label: str,
        scopes: str = "read",
        rate_limit_per_minute: int = 60,
        notes: str | None = None,
    ) -> str:
        key_id = secrets.token_hex(8)
        self._c.execute(
            """
            INSERT INTO api_keys
                (id, key_hash, prefix, label, scopes, rate_limit_per_minute, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (key_id, key_hash, prefix, label, scopes, rate_limit_per_minute, notes),
        )
        return key_id

    def list_all(self) -> list[dict[str, Any]]:
        """List keys WITHOUT key_hash — never expose the hash or raw key here."""
        rows = self._c.execute(
            """
            SELECT id, prefix, label, scopes, rate_limit_per_minute, notes,
                   created_at, last_used_at, revoked
            FROM api_keys
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def revoke(self, key_id: str) -> bool:
        cur = self._c.execute(
            "UPDATE api_keys SET revoked = 1 WHERE id = ? AND revoked = 0", (key_id,)
        )
        return cur.rowcount > 0

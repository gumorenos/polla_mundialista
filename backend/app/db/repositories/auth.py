from __future__ import annotations

import sqlite3


def has_password_change_history(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT COUNT(*) FROM admin_password_history"
    ).fetchone()[0] > 0


def insert_password_history(
    conn: sqlite3.Connection,
    changed_by: str,
    password_hash: str,
    note: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO admin_password_history (changed_by, password_hash, note)
        VALUES (?, ?, ?)
        """,
        (changed_by, password_hash, note),
    )

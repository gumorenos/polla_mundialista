from __future__ import annotations

import sqlite3


def insert_password_history(conn: sqlite3.Connection, changed_by: str, password_hash: str) -> None:
    conn.execute(
        "INSERT INTO admin_password_history (changed_by, password_hash) VALUES (?, ?)",
        (changed_by, password_hash),
    )

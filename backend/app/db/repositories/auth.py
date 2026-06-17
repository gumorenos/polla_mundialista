from __future__ import annotations

import sqlite3

ADMIN_CREDENTIAL_ID = "admin"


def get_admin_password_hash(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT password_hash FROM admin_credentials WHERE id = ?",
        (ADMIN_CREDENTIAL_ID,),
    ).fetchone()
    return row["password_hash"] if row else None


def has_admin_credential(conn: sqlite3.Connection) -> bool:
    return get_admin_password_hash(conn) is not None


def upsert_admin_credential(conn: sqlite3.Connection, password_hash: str) -> None:
    conn.execute(
        """
        INSERT INTO admin_credentials (id, password_hash)
        VALUES (?, ?)
        ON CONFLICT(id) DO UPDATE SET
            password_hash = excluded.password_hash,
            updated_at = CURRENT_TIMESTAMP
        """,
        (ADMIN_CREDENTIAL_ID, password_hash),
    )


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

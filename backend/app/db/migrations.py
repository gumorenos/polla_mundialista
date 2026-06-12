"""Idempotent schema migrations — CREATE TABLE IF NOT EXISTS only, never DROP.

Each migration function is safe to run multiple times. Called once at startup
via the FastAPI lifespan. Schema grows prompt-by-prompt.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.db.connection import db_transaction

logger = get_logger(__name__)


def _m001_jobs_table(conn) -> None:
    """Minimal jobs table — tracks background RQ job metadata."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id          TEXT PRIMARY KEY,
            queue       TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'enqueued',
            func_name   TEXT,
            created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            started_at  TEXT,
            ended_at    TEXT,
            result      TEXT,
            error       TEXT
        )
        """
    )


_MIGRATIONS = [_m001_jobs_table]


def run_migrations() -> None:
    """Apply all pending migrations in order."""
    logger.info("Running DB migrations…")
    with db_transaction() as conn:
        for fn in _MIGRATIONS:
            logger.debug("Applying migration: %s", fn.__name__)
            fn(conn)
    logger.info("DB migrations complete (%d applied)", len(_MIGRATIONS))

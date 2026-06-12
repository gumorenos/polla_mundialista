"""Shared test configuration and fixtures.

- Generates historical_results.csv before the session if the file is missing
  or has fewer than 500 data rows.
- Provides a shared `db` fixture (in-memory SQLite with migrations applied)
  for both test_db.py and test_ingestion.py.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ensure seed data exists before any test runs
# ---------------------------------------------------------------------------

_DATA_RAW = Path(__file__).parent.parent.parent / "data" / "raw"
_HIST_CSV  = _DATA_RAW / "historical_results.csv"


def _row_count(path: Path) -> int:
    with path.open(encoding="utf-8") as f:
        return sum(1 for _ in f) - 1  # minus header


def pytest_configure(config):
    """Generate historical CSV if missing or too small (< 500 data rows)."""
    if not _HIST_CSV.exists() or _row_count(_HIST_CSV) < 500:
        import sys
        gen = _DATA_RAW / "generate_historical.py"
        if gen.exists():
            import subprocess
            subprocess.run([sys.executable, str(gen)], check=True)


# ---------------------------------------------------------------------------
# Shared in-memory DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db() -> sqlite3.Connection:
    """In-memory SQLite with all migrations applied. Module-scoped for speed."""
    from app.db.migrations import run_migrations

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    yield conn
    conn.close()

"""GET /api/news/summary must surface the source link for an active injury
claim, or an explicit note when no source is linked — never drop it
silently (see app/api/routes/news.py::news_summary)."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.db.migrations import run_migrations


def _insert_claim(conn, claim_id, team_id, player, source_url, source_name):
    conn.execute(
        """
        INSERT INTO availability_claims
            (id, team_id, player_name, status, observed_at, affects_prediction,
             source_url, source_name, published_at)
        VALUES (?, ?, ?, 'injured', '2026-06-01T00:00:00Z', 1, ?, ?, '2026-06-01T00:00:00Z')
        """,
        (claim_id, team_id, player, source_url, source_name),
    )


@pytest.fixture()
def client(monkeypatch, tmp_path):
    db_path = str(tmp_path / "summary.db")
    monkeypatch.setattr("app.core.config.settings.SCHEDULER_ENABLED", False)
    monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    conn.execute("INSERT OR IGNORE INTO teams (id, name, created_at) VALUES ('ARG', 'Argentina', '2026-01-01')")
    conn.execute("INSERT OR IGNORE INTO teams (id, name, created_at) VALUES ('BRA', 'Brazil', '2026-01-01')")
    _insert_claim(conn, "c1", "ARG", "Messi", "https://espn.com/injury", "ESPN")
    _insert_claim(conn, "c2", "BRA", "Neymar", None, None)
    conn.commit()
    conn.close()

    from app.main import app
    return TestClient(app)


def test_injury_with_source_shows_link(client):
    resp = client.get("/api/news/summary")
    assert resp.status_code == 200
    teams = resp.json()["teams"]
    arg = next(t for t in teams if t["team_id"] == "ARG")
    assert arg["source_url"] == "https://espn.com/injury"
    assert arg["source_name"] == "ESPN"


def test_injury_without_source_has_explicit_fallback(client):
    resp = client.get("/api/news/summary")
    teams = resp.json()["teams"]
    bra = next(t for t in teams if t["team_id"] == "BRA")
    assert bra["source_url"] is None
    assert bra["source_note"] == "Sin fuente enlazada en availability_claims"

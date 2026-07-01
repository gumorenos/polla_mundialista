"""Tests for GET /api/news/player-form — squad-filtered key player + metadata."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.db.migrations import run_migrations


def _bootstrap(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    conn.execute("INSERT OR IGNORE INTO teams (id, name, created_at) VALUES ('ARG', 'Argentina', '2026-01-01')")

    def _match(mid):
        conn.execute(
            """INSERT OR IGNORE INTO sb_matches
               (match_id, competition_id, season_id, competition_name, season_name,
                match_date, home_team_id, away_team_id, home_score, away_score,
                home_team_sb, away_team_sb)
               VALUES (?, 43, 106, 'WC', '2022', '2022-12-01', 'ARG', 'FRA', 1, 0, 'Argentina', 'France')""",
            (mid,),
        )

    def _stat(mid, player, xg):
        _match(mid)
        pid = f"{mid}_{player}"[:16]
        conn.execute(
            """INSERT OR IGNORE INTO sb_player_stats
               (id, match_id, team_id, player_name, position, minutes_played, goals, xg, shots, key_passes)
               VALUES (?, ?, 'ARG', ?, 'Forward', 90, 0, ?, 2, 1)""",
            (pid, mid, player, xg),
        )

    _stat(1, "OldStar", 0.9)   # highest xG, but NOT in squad
    _stat(2, "Rookie", 0.3)    # lower xG, but IS in squad
    conn.execute("INSERT OR IGNORE INTO wc2026_squads (team_id, player_name) VALUES ('ARG', 'Rookie')")
    conn.commit()
    conn.close()


@pytest.fixture()
def client(monkeypatch, tmp_path):
    db_path = str(tmp_path / "pf.db")
    monkeypatch.setattr("app.core.config.settings.SCHEDULER_ENABLED", False)
    monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)
    _bootstrap(db_path)

    from app.main import app
    return TestClient(app)


def test_key_player_restricted_to_real_squad(client):
    resp = client.get("/api/news/player-form")
    assert resp.status_code == 200
    teams = resp.json()["teams"]
    arg = next(t for t in teams if t["team_id"] == "ARG")

    # Rookie is in the squad (even with lower xG) — must be picked, not OldStar.
    assert arg["key_player"] == "Rookie"
    assert arg["squad_status"] == "confirmed"
    assert arg["uses_fallback_player_pool"] is False
    assert arg["squad_warning"] is None


@pytest.fixture()
def client_partial_squad(monkeypatch, tmp_path):
    """A team with a wc2026_squads row that matches none of its StatsBomb
    player names — squad_status='partial', no key player resolvable."""
    db_path = str(tmp_path / "pf_partial.db")
    monkeypatch.setattr("app.core.config.settings.SCHEDULER_ENABLED", False)
    monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    conn.execute("INSERT OR IGNORE INTO teams (id, name, created_at) VALUES ('BRA', 'Brazil', '2026-01-01')")
    conn.execute(
        """INSERT OR IGNORE INTO sb_matches
           (match_id, competition_id, season_id, competition_name, season_name,
            match_date, home_team_id, away_team_id, home_score, away_score,
            home_team_sb, away_team_sb)
           VALUES (1, 43, 106, 'WC', '2022', '2022-12-01', 'BRA', 'FRA', 1, 0, 'Brazil', 'France')"""
    )
    conn.execute(
        """INSERT OR IGNORE INTO sb_player_stats
           (id, match_id, team_id, player_name, position, minutes_played, goals, xg, shots, key_passes)
           VALUES ('1_x', 1, 'BRA', 'Legacy Striker', 'Forward', 90, 0, 0.5, 2, 1)"""
    )
    # Squad name that matches nothing in sb_player_stats, even normalized.
    conn.execute("INSERT OR IGNORE INTO wc2026_squads (team_id, player_name) VALUES ('BRA', 'Totally Different Name')")
    conn.commit()
    conn.close()

    from app.main import app
    return TestClient(app)


def test_team_with_no_resolvable_key_player_is_not_silently_dropped(client_partial_squad):
    """Before this fix, a team whose squad couldn't be matched against
    StatsBomb records vanished from the response entirely — the frontend
    then showed a blank page with no explanation. It must still appear,
    with key_player=None and a warning."""
    resp = client_partial_squad.get("/api/news/player-form")
    assert resp.status_code == 200
    body = resp.json()
    bra = next(t for t in body["teams"] if t["team_id"] == "BRA")

    assert bra["key_player"] is None
    assert bra["squad_status"] == "partial"
    assert bra["squad_warning"]
    assert "key_players_count" in body
    assert "squads_available" in body

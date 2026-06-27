"""Tests for player form scoring and team form adjustment."""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.features.player_form import (
    _IN_FORM_BONUS,
    _IN_FORM_THRESHOLD,
    _OUT_OF_FORM_PENALTY,
    _OUT_OF_FORM_THRESH,
    get_player_form,
    get_team_form_adjustment,
)


@pytest.fixture
def mem_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    for tid, name in [("ARG", "Argentina"), ("FRA", "France"), ("GER", "Germany")]:
        conn.execute(
            "INSERT OR IGNORE INTO teams (id, name, created_at) VALUES (?, ?, '2026-01-01')",
            (tid, name),
        )
    conn.commit()
    yield conn
    conn.close()


def _insert_match(conn, match_id, team_id="ARG", date="2022-12-01"):
    conn.execute(
        """INSERT OR IGNORE INTO sb_matches
           (match_id, competition_id, season_id, competition_name, season_name,
            match_date, home_team_id, away_team_id, home_score, away_score,
            home_team_sb, away_team_sb)
           VALUES (?, 43, 106, 'FIFA World Cup', '2022', ?, ?, 'FRA', 1, 0, ?, 'France')""",
        (match_id, date, team_id, team_id),
    )


def _insert_player_stat(conn, match_id, player, team_id="ARG", xg=0.0, goals=0, shots=0, key_passes=0):
    pid = f"{match_id}_{player}_{team_id}"[:16]
    conn.execute(
        """INSERT OR IGNORE INTO sb_player_stats
           (id, match_id, team_id, player_name, position, minutes_played, goals, xg, shots, key_passes)
           VALUES (?, ?, ?, ?, 'Forward', 90, ?, ?, ?, ?)""",
        (pid, match_id, team_id, player, goals, xg, shots, key_passes),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# get_player_form
# ---------------------------------------------------------------------------

def test_player_form_no_data_returns_has_data_false(mem_db):
    result = get_player_form("Messi", "ARG", mem_db)
    assert result["has_data"] is False
    assert result["form_rating"] == 0.0


def test_player_form_single_match(mem_db):
    _insert_match(mem_db, 1001)
    _insert_player_stat(mem_db, 1001, "Messi", xg=0.6, goals=1)
    result = get_player_form("Messi", "ARG", mem_db)
    assert result["has_data"] is True
    assert result["matches_used"] == 1
    assert abs(result["avg_xg"] - 0.6) < 0.01
    assert abs(result["avg_goals"] - 1.0) < 0.01


def test_player_form_rating_normalized(mem_db):
    """form_rating = avg_xg / 0.3, so xg=0.3 → rating=1.0."""
    _insert_match(mem_db, 2001)
    _insert_player_stat(mem_db, 2001, "Striker", xg=0.3)
    result = get_player_form("Striker", "ARG", mem_db)
    assert abs(result["form_rating"] - 1.0) < 0.01


def test_player_form_in_form(mem_db):
    """xg=0.6 → form_rating=2.0 → in_form=True."""
    for i in range(3):
        _insert_match(mem_db, 3000 + i, date=f"2022-12-{i+1:02d}")
        _insert_player_stat(mem_db, 3000 + i, "Star", xg=0.6)
    result = get_player_form("Star", "ARG", mem_db)
    assert result["in_form"] is True
    assert result["out_of_form"] is False
    assert result["form_rating"] > _IN_FORM_THRESHOLD


def test_player_form_out_of_form(mem_db):
    """xg=0.05 → form_rating≈0.17 → out_of_form=True."""
    for i in range(3):
        _insert_match(mem_db, 4000 + i, date=f"2022-12-{i+1:02d}")
        _insert_player_stat(mem_db, 4000 + i, "Benched", xg=0.05)
    result = get_player_form("Benched", "ARG", mem_db)
    assert result["out_of_form"] is True
    assert result["in_form"] is False
    assert result["form_rating"] < _OUT_OF_FORM_THRESH


def test_player_form_last_n_respected(mem_db):
    """last_n=2 should only use the 2 most recent matches."""
    for i in range(5):
        _insert_match(mem_db, 5000 + i, date=f"2022-12-{i+1:02d}")
        xg = 1.5 if i >= 3 else 0.1   # last 2 have high xG
        _insert_player_stat(mem_db, 5000 + i, "Player", xg=xg)
    result = get_player_form("Player", "ARG", mem_db, last_n=2)
    assert result["matches_used"] == 2
    assert result["avg_xg"] > 1.0


def test_player_form_isolated_per_team(mem_db):
    """Same player name in different teams should not bleed across."""
    _insert_match(mem_db, 6001, team_id="ARG")
    _insert_player_stat(mem_db, 6001, "Clone", team_id="ARG", xg=0.9)
    result_fra = get_player_form("Clone", "FRA", mem_db)
    assert result_fra["has_data"] is False


# ---------------------------------------------------------------------------
# get_team_form_adjustment
# ---------------------------------------------------------------------------

def test_team_form_no_data_returns_one(mem_db):
    factor = get_team_form_adjustment("ARG", mem_db)
    assert factor == 1.0


def test_team_form_in_form_returns_bonus(mem_db):
    for i in range(3):
        _insert_match(mem_db, 7000 + i, date=f"2022-12-{i+1:02d}")
        _insert_player_stat(mem_db, 7000 + i, "TopStriker", xg=0.9)
    factor = get_team_form_adjustment("ARG", mem_db)
    assert factor == _IN_FORM_BONUS


def test_team_form_out_of_form_returns_penalty(mem_db):
    for i in range(3):
        _insert_match(mem_db, 8000 + i, date=f"2022-12-{i+1:02d}")
        _insert_player_stat(mem_db, 8000 + i, "ColdStriker", xg=0.04)
    factor = get_team_form_adjustment("ARG", mem_db)
    assert factor == _OUT_OF_FORM_PENALTY


def test_team_form_uses_highest_xg_player(mem_db):
    """The adjustment should be based on the player with most xG, not first alphabetically."""
    _insert_match(mem_db, 9001)
    _insert_player_stat(mem_db, 9001, "AAA_Low",  xg=0.05)  # very low — out of form
    _insert_player_stat(mem_db, 9001, "ZZZ_High", xg=0.9)   # high — in form
    # ZZZ_High has more xG so should be the key player → in_form → bonus
    factor = get_team_form_adjustment("ARG", mem_db)
    assert factor == _IN_FORM_BONUS


# ---------------------------------------------------------------------------
# Statsbomb loader: minutes_played from substitution events
# ---------------------------------------------------------------------------

def test_parse_match_events_player_stats_minutes():
    """parse_match_events is team-level; test _ingest_player_stats via import."""
    import hashlib
    from app.services.ingestion.statsbomb_loader import _ingest_player_stats

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, name, created_at) VALUES ('ARG', 'Argentina', '2026-01-01')"
    )
    conn.execute(
        """INSERT OR IGNORE INTO sb_matches
           (match_id, competition_id, season_id, competition_name, season_name,
            match_date, home_team_id, away_team_id, home_score, away_score,
            home_team_sb, away_team_sb)
           VALUES (99, 43, 106, 'WC', '2022', '2022-12-01', 'ARG', 'FRA', 1, 0,
                   'Argentina', 'France')"""
    )
    conn.commit()

    events = [
        {"type": {"name": "Shot"}, "team": {"name": "Argentina"},
         "player": {"name": "Messi"}, "position": {"name": "Forward"},
         "minute": 30,
         "shot": {"statsbomb_xg": 0.5, "outcome": {"name": "Goal"}}},
        {"type": {"name": "Substitution"}, "team": {"name": "Argentina"},
         "player": {"name": "Messi"}, "position": {"name": "Forward"}, "minute": 75,
         "substitution": {"replacement": {"name": "Sub"}}},
    ]

    _ingest_player_stats(conn, 99, events)
    conn.commit()

    row = conn.execute(
        "SELECT minutes_played, xg, goals FROM sb_player_stats WHERE player_name='Messi'"
    ).fetchone()
    assert row is not None
    assert row["minutes_played"] == 75
    assert abs(row["xg"] - 0.5) < 0.01
    assert row["goals"] == 1
    conn.close()

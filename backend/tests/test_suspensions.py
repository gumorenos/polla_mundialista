"""Tests for player booking ingestion and suspension detection."""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.suspensions.detector import get_suspended_players


@pytest.fixture
def mem_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    # Insert a dummy team so FK constraints pass
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, name, created_at) VALUES ('FRA', 'Francia', '2026-01-01')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, name, created_at) VALUES ('ARG', 'Argentina', '2026-01-01')"
    )
    conn.commit()
    yield conn
    conn.close()


def _insert_booking(conn, player_name, team_id, card_type, match_date="2026-06-15", competition="WC2026"):
    conn.execute(
        "INSERT INTO player_bookings (id, player_name, team_id, card_type, match_date, competition)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (f"{competition}_{team_id}_{player_name}_{card_type}_{match_date}", player_name, team_id, card_type, match_date, competition),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# detector.get_suspended_players
# ---------------------------------------------------------------------------

def test_no_suspensions_when_no_bookings(mem_db):
    """No bookings → no suspensions."""
    result = get_suspended_players("FRA", mem_db)
    assert result == []


def test_one_yellow_not_suspended(mem_db):
    """1 yellow card alone does not trigger a suspension."""
    _insert_booking(mem_db, "Griezmann", "FRA", "YELLOW")
    result = get_suspended_players("FRA", mem_db)
    assert result == []


def test_two_yellows_suspended(mem_db):
    """2 yellow cards → player is suspended."""
    _insert_booking(mem_db, "Griezmann", "FRA", "YELLOW", "2026-06-15")
    _insert_booking(mem_db, "Griezmann", "FRA", "YELLOW", "2026-06-20")
    result = get_suspended_players("FRA", mem_db)
    assert len(result) == 1
    assert result[0]["player_name"] == "Griezmann"
    assert result[0]["card_type"] == "YELLOW"


def test_red_card_suspended(mem_db):
    """RED card → immediate suspension."""
    _insert_booking(mem_db, "Mbappé", "FRA", "RED")
    result = get_suspended_players("FRA", mem_db)
    assert len(result) == 1
    assert result[0]["player_name"] == "Mbappé"
    assert result[0]["card_type"] == "RED"


def test_yellow_red_suspended(mem_db):
    """YELLOW_RED (double yellow) → suspended."""
    _insert_booking(mem_db, "Dembélé", "FRA", "YELLOW_RED")
    result = get_suspended_players("FRA", mem_db)
    assert len(result) == 1
    assert result[0]["card_type"] == "RED"


def test_player_with_red_not_duplicated_in_yellow_suspension(mem_db):
    """Player with 2 yellows AND a red card is listed only once."""
    _insert_booking(mem_db, "Varane", "FRA", "YELLOW", "2026-06-10")
    _insert_booking(mem_db, "Varane", "FRA", "YELLOW", "2026-06-15")
    _insert_booking(mem_db, "Varane", "FRA", "RED", "2026-06-20")
    result = get_suspended_players("FRA", mem_db)
    names = [p["player_name"] for p in result]
    assert names.count("Varane") == 1


def test_suspensions_isolated_per_team(mem_db):
    """Bookings for team ARG don't affect FRA suspensions."""
    _insert_booking(mem_db, "Messi", "ARG", "YELLOW", "2026-06-15")
    _insert_booking(mem_db, "Messi", "ARG", "YELLOW", "2026-06-20")
    assert get_suspended_players("FRA", mem_db) == []
    arg_susp = get_suspended_players("ARG", mem_db)
    assert len(arg_susp) == 1
    assert arg_susp[0]["player_name"] == "Messi"


def test_other_competitions_ignored(mem_db):
    """Bookings from other competitions (e.g. qualifiers) are not counted."""
    _insert_booking(mem_db, "Theo", "FRA", "YELLOW", competition="UEFA")
    _insert_booking(mem_db, "Theo", "FRA", "YELLOW", competition="FRIENDLY")
    # Only 0 WC2026 yellows → no suspension
    assert get_suspended_players("FRA", mem_db) == []


def test_multiple_suspended_players(mem_db):
    """Multiple players with different card types all appear in results."""
    _insert_booking(mem_db, "Griezmann", "FRA", "YELLOW", "2026-06-10")
    _insert_booking(mem_db, "Griezmann", "FRA", "YELLOW", "2026-06-15")
    _insert_booking(mem_db, "Camavinga", "FRA", "RED", "2026-06-18")
    result = get_suspended_players("FRA", mem_db)
    names = {p["player_name"] for p in result}
    assert names == {"Griezmann", "Camavinga"}


# ---------------------------------------------------------------------------
# run_suspension_analysis integration
# ---------------------------------------------------------------------------

def test_run_suspension_analysis_no_bookings(mem_db):
    """With no bookings, suspension analysis reports no affected teams."""
    from app.services.news.availability import run_suspension_analysis
    result = run_suspension_analysis(mem_db)
    assert result["affected_teams"] == []
    assert result["suspended_players"] == []


def test_run_suspension_analysis_inserts_adjustment(mem_db):
    """Suspended players cause a team_context_adjustments row."""
    _insert_booking(mem_db, "Griezmann", "FRA", "YELLOW", "2026-06-10")
    _insert_booking(mem_db, "Griezmann", "FRA", "YELLOW", "2026-06-15")

    from app.services.news.availability import run_suspension_analysis
    result = run_suspension_analysis(mem_db)

    assert "FRA" in result["affected_teams"]

    row = mem_db.execute(
        "SELECT * FROM team_context_adjustments WHERE team_id='FRA' AND adjustment_type='suspension'"
    ).fetchone()
    assert row is not None
    assert row["attack_factor"] < 1.0   # penalty applied
    assert row["defense_factor"] > 1.0  # vulnerability increased


# ---------------------------------------------------------------------------
# player_bookings table (migration check)
# ---------------------------------------------------------------------------

def test_player_bookings_table_exists(mem_db):
    """The player_bookings table is created by migration 014."""
    result = mem_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='player_bookings'"
    ).fetchone()
    assert result is not None


def test_player_bookings_unique_id(mem_db):
    """Inserting the same booking ID twice is silently ignored (OR IGNORE)."""
    mem_db.execute(
        "INSERT INTO player_bookings (id, player_name, team_id, card_type, match_date)"
        " VALUES ('abc', 'Mbappé', 'FRA', 'YELLOW', '2026-06-15')"
    )
    mem_db.commit()
    mem_db.execute(
        "INSERT OR IGNORE INTO player_bookings (id, player_name, team_id, card_type, match_date)"
        " VALUES ('abc', 'Mbappé', 'FRA', 'YELLOW', '2026-06-15')"
    )
    mem_db.commit()
    count = mem_db.execute("SELECT COUNT(*) FROM player_bookings WHERE id='abc'").fetchone()[0]
    assert count == 1

"""Tests for altitude/host-team advantage adjustment."""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.features.altitude_adjustment import (
    _HIGH_ALTITUDE_TEAMS,
    _HOST_BONUS,
    _MAX_PENALTY,
    get_altitude_adjustment,
)


@pytest.fixture
def mem_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    # Insert test teams
    for tid, name in [("MEX", "Mexico"), ("GER", "Germany"), ("COL", "Colombia"),
                      ("USA", "United States"), ("FRA", "France"), ("ECU", "Ecuador")]:
        conn.execute(
            "INSERT OR IGNORE INTO teams (id, name, created_at) VALUES (?, ?, '2026-01-01')",
            (tid, name),
        )
    conn.commit()
    yield conn
    conn.close()


def _insert_venue(conn, venue_id, altitude_m, host_team_id=None):
    conn.execute(
        """INSERT OR REPLACE INTO venues (venue_id, venue_name, city, country, altitude_m, host_team_id)
           VALUES (?, ?, 'City', 'XX', ?, ?)""",
        (venue_id, f"Stadium {venue_id}", altitude_m, host_team_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Basic behaviour
# ---------------------------------------------------------------------------

def test_returns_none_for_unknown_venue(mem_db):
    result = get_altitude_adjustment("GER", "UNKNOWN", mem_db)
    assert result is None


def test_no_penalty_at_sea_level(mem_db):
    _insert_venue(mem_db, "NYC", altitude_m=10)
    result = get_altitude_adjustment("GER", "NYC", mem_db)
    assert result is not None
    assert result["altitude_adjustment"] == 1.0
    assert result["host_bonus"] == 1.0
    assert result["combined"] == 1.0


def test_no_penalty_below_threshold(mem_db):
    _insert_venue(mem_db, "ATL", altitude_m=309)
    result = get_altitude_adjustment("GER", "ATL", mem_db)
    assert result["altitude_adjustment"] == 1.0


# ---------------------------------------------------------------------------
# Altitude penalty
# ---------------------------------------------------------------------------

def test_penalty_applied_above_1000m(mem_db):
    _insert_venue(mem_db, "AZT", altitude_m=2240)
    result = get_altitude_adjustment("GER", "AZT", mem_db)
    assert result is not None
    assert result["altitude_adjustment"] < 1.0
    # Expected: (2240/1000) * 3.5% = 7.84% penalty → factor 0.9216
    expected = 1.0 - (2240 / 1000 * 0.035)
    assert abs(result["altitude_adjustment"] - expected) < 0.001


def test_penalty_capped_at_max(mem_db):
    # Altitude so high the raw penalty exceeds _MAX_PENALTY
    _insert_venue(mem_db, "HIGH", altitude_m=5000)
    result = get_altitude_adjustment("GER", "HIGH", mem_db)
    assert result is not None
    assert result["altitude_adjustment"] == round(1.0 - _MAX_PENALTY, 4)


def test_high_altitude_team_no_penalty(mem_db):
    """MEX and COL are accustomed to altitude — no penalty at Azteca."""
    _insert_venue(mem_db, "AZT", altitude_m=2240)
    for team_id in ["MEX", "COL", "ECU"]:
        result = get_altitude_adjustment(team_id, "AZT", mem_db)
        assert result is not None, f"{team_id} should return result"
        assert result["altitude_adjustment"] == 1.0, f"{team_id} should have no penalty"


# ---------------------------------------------------------------------------
# Host-team bonus
# ---------------------------------------------------------------------------

def test_host_bonus_applied(mem_db):
    _insert_venue(mem_db, "NRG", altitude_m=15, host_team_id="USA")
    result = get_altitude_adjustment("USA", "NRG", mem_db)
    assert result is not None
    assert result["host_bonus"] == round(1.0 + _HOST_BONUS, 4)
    assert result["combined"] == round(1.0 + _HOST_BONUS, 4)


def test_no_host_bonus_for_visitor(mem_db):
    _insert_venue(mem_db, "NRG", altitude_m=15, host_team_id="USA")
    result = get_altitude_adjustment("GER", "NRG", mem_db)
    assert result["host_bonus"] == 1.0


def test_no_host_bonus_when_no_host_team(mem_db):
    _insert_venue(mem_db, "NEUTRAL", altitude_m=0, host_team_id=None)
    result = get_altitude_adjustment("GER", "NEUTRAL", mem_db)
    assert result["host_bonus"] == 1.0


# ---------------------------------------------------------------------------
# Combined factor
# ---------------------------------------------------------------------------

def test_combined_altitude_penalty_and_host_bonus(mem_db):
    """MEX at Azteca: no altitude penalty + host bonus."""
    _insert_venue(mem_db, "AZT", altitude_m=2240, host_team_id="MEX")
    result = get_altitude_adjustment("MEX", "AZT", mem_db)
    assert result["altitude_adjustment"] == 1.0
    assert result["host_bonus"] == round(1.0 + _HOST_BONUS, 4)
    assert result["combined"] == round(1.0 + _HOST_BONUS, 4)


def test_combined_penalty_no_bonus(mem_db):
    """FRA at Azteca: altitude penalty, no host bonus."""
    _insert_venue(mem_db, "AZT", altitude_m=2240, host_team_id="MEX")
    result = get_altitude_adjustment("FRA", "AZT", mem_db)
    expected_adj = round(1.0 - (2240 / 1000 * 0.035), 4)
    assert result["altitude_adjustment"] == expected_adj
    assert result["host_bonus"] == 1.0
    assert result["combined"] == expected_adj


def test_altitude_m_returned_correctly(mem_db):
    _insert_venue(mem_db, "EST", altitude_m=1566)
    result = get_altitude_adjustment("GER", "EST", mem_db)
    assert result["altitude_m"] == 1566.0


# ---------------------------------------------------------------------------
# high_altitude_teams set
# ---------------------------------------------------------------------------

def test_high_altitude_teams_set_contains_expected():
    assert "MEX" in _HIGH_ALTITUDE_TEAMS
    assert "COL" in _HIGH_ALTITUDE_TEAMS
    assert "ECU" in _HIGH_ALTITUDE_TEAMS
    assert "BOL" in _HIGH_ALTITUDE_TEAMS
    assert "GER" not in _HIGH_ALTITUDE_TEAMS

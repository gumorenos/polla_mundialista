"""Tests for app.services.features.strengths — team strength calculator."""

from __future__ import annotations

import math
import sqlite3
import uuid
from datetime import date

import pytest

from app.db.migrations import run_migrations
from app.db.repositories.strengths import StrengthRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_with_data() -> sqlite3.Connection:
    """In-memory DB with teams, ELO ratings, and historical results loaded."""
    from app.services.ingestion.csv_loader import load_teams_from_csv, load_ratings_from_csv
    from app.services.ingestion.csv_loader import load_historical_results_from_csv

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    load_teams_from_csv(conn=conn)
    conn.commit()
    load_ratings_from_csv(conn=conn)
    conn.commit()
    load_historical_results_from_csv(conn=conn)
    conn.commit()
    yield conn
    conn.close()


def _make_minimal_db() -> sqlite3.Connection:
    """Return an in-memory DB with 3 teams and a handful of crafted results."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)

    teams = [
        ("T1", "Alpha"),
        ("T2", "Beta"),
        ("T3", "Gamma"),
    ]
    for tid, name in teams:
        conn.execute(
            "INSERT INTO teams (id, name) VALUES (?, ?)", (tid, name)
        )

    # Two matches: T1 vs T2 and T2 vs T3
    matches = [
        (str(uuid.uuid4()), "T1", "T2", 3, 1, "2024-01-01"),
        (str(uuid.uuid4()), "T2", "T3", 2, 0, "2024-01-15"),
    ]
    for mid, home, away, hg, ag, dt in matches:
        conn.execute(
            """INSERT INTO results
               (id, home_team_id, away_team_id, home_goals, away_goals, match_date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (mid, home, away, hg, ag, dt),
        )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# 1. All teams get a strength entry after calculation
# ---------------------------------------------------------------------------

class TestAllTeamsGetEntry:
    def test_every_team_has_strength(self, db_with_data):
        from app.services.features.strengths import calculate_team_strengths

        calculate_team_strengths(db_with_data)

        team_ids = {
            r["id"]
            for r in db_with_data.execute("SELECT id FROM teams").fetchall()
        }
        repo = StrengthRepository(db_with_data)
        strength_ids = {s["team_id"] for s in repo.get_all()}

        missing = team_ids - strength_ids
        assert not missing, f"Teams without strength entry: {missing}"


# ---------------------------------------------------------------------------
# 2. attack and defense are in [0.3, 3.0] for all teams
# ---------------------------------------------------------------------------

class TestStrengthBounds:
    def test_attack_in_range(self, db_with_data):
        from app.services.features.strengths import calculate_team_strengths

        result = calculate_team_strengths(db_with_data)
        for tid, s in result.items():
            assert 0.3 <= s["attack_strength"] <= 3.0, (
                f"Team {tid} attack out of range: {s['attack_strength']}"
            )

    def test_defense_in_range(self, db_with_data):
        from app.services.features.strengths import calculate_team_strengths

        result = calculate_team_strengths(db_with_data)
        for tid, s in result.items():
            assert 0.3 <= s["defense_vulnerability"] <= 3.0, (
                f"Team {tid} defense out of range: {s['defense_vulnerability']}"
            )


# ---------------------------------------------------------------------------
# 3. decay_factor=0 → all weights equal 1.0 → simple average
# ---------------------------------------------------------------------------

class TestZeroDecay:
    def test_zero_decay_gives_equal_weights(self):
        """With decay=0 every match weight is exp(0)=1 regardless of date."""
        from app.services.features.strengths import calculate_team_strengths

        conn = _make_minimal_db()
        result = calculate_team_strengths(
            conn,
            as_of_date=date(2025, 1, 1),
            decay_factor=0.0,
        )

        # T1 played 1 match (home, 3-1). Goals for=3, against=1.
        # T2 played 2 matches: (away, 1-3) + (home, 2-0).
        # T3 played 1 match (away, 0-2). Goals for=0, against=2.
        # With no ELO data, rival_factor = 1 + 1500/3000 = 1.5 for all.
        # Weights all = 1.0 (zero decay).
        # T1 raw_attack = (3 * 1 * 1.5) / 1 = 4.5
        # T3 raw_attack = (0 * 1 * 1.5) / 1 = 0.0
        # global mean_atk = mean of all non-None raw values
        # Just verify T3 (no goals scored) has lower attack than T1.
        assert result["T1"]["attack_strength"] > result["T3"]["attack_strength"]

        # Also verify matches_used is correct for T2 (2 matches)
        assert result["T2"]["matches_used"] == 2

        conn.close()

    def test_zero_decay_matches_used_equals_matches_total(self):
        """With decay=0 every match has weight=1 > _MIN_WEIGHT, so all count."""
        from app.services.features.strengths import calculate_team_strengths

        conn = _make_minimal_db()
        result = calculate_team_strengths(
            conn,
            as_of_date=date(2025, 1, 1),
            decay_factor=0.0,
        )
        # T1 has 1 match, matches_used should be 1
        assert result["T1"]["matches_used"] == 1
        conn.close()


# ---------------------------------------------------------------------------
# 4. Team with no history → neutral values, no crash
# ---------------------------------------------------------------------------

class TestNoHistoryTeam:
    def test_no_history_returns_neutral(self):
        """A team present in teams table but absent from results gets 1.0/1.0."""
        from app.services.features.strengths import calculate_team_strengths

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        run_migrations(conn)

        # Insert one team with NO results
        conn.execute("INSERT INTO teams (id, name) VALUES ('LONE', 'Lonelyland FC')")
        conn.commit()

        result = calculate_team_strengths(conn)
        assert "LONE" in result
        s = result["LONE"]
        assert s["attack_strength"] == pytest.approx(1.0)
        assert s["defense_vulnerability"] == pytest.approx(1.0)
        assert s["data_quality_score"] == 0.0
        assert s["matches_used"] == 0

        conn.close()

    def test_no_history_does_not_crash(self):
        """calculate_team_strengths must not raise for a history-less team."""
        from app.services.features.strengths import calculate_team_strengths

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        run_migrations(conn)
        conn.execute("INSERT INTO teams (id, name) VALUES ('GHOST', 'Ghost United')")
        conn.commit()

        try:
            calculate_team_strengths(conn)
        except Exception as exc:
            pytest.fail(f"calculate_team_strengths raised {exc!r} for history-less team")

        conn.close()

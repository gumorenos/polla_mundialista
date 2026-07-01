"""Tests for get_alive_team_ids — used to filter news/key-players to teams
still alive in the tournament."""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.features.alive_teams import get_alive_team_ids


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    return conn


class TestFallbackNoData:
    def test_falls_back_to_is_wc2026_with_warning(self):
        conn = _make_db()
        conn.execute("INSERT INTO teams (id, name, is_wc2026) VALUES ('ARG', 'Argentina', 1)")
        conn.execute("INSERT INTO teams (id, name, is_wc2026) VALUES ('OLD', 'Retired Team', 0)")
        conn.commit()

        alive, warning = get_alive_team_ids(conn)

        assert alive == {"ARG"}
        assert warning is not None
        conn.close()


class TestStandingsBased:
    def test_eliminated_excluded_active_included(self):
        conn = _make_db()
        conn.execute("INSERT INTO teams (id, name) VALUES ('ARG', 'Argentina')")
        conn.execute("INSERT INTO teams (id, name) VALUES ('OUT', 'Eliminated Team')")
        conn.execute(
            "INSERT INTO wc2026_standings (team_id, group_id, position, status) VALUES ('ARG', 'A', 1, 'active')"
        )
        conn.execute(
            "INSERT INTO wc2026_standings (team_id, group_id, position, status) VALUES ('OUT', 'A', 4, 'eliminated')"
        )
        conn.commit()

        alive, warning = get_alive_team_ids(conn)

        assert alive == {"ARG"}
        assert warning is None
        conn.close()

    def test_qualified_status_counts_as_alive(self):
        conn = _make_db()
        conn.execute("INSERT INTO teams (id, name) VALUES ('BRA', 'Brasil')")
        conn.execute(
            "INSERT INTO wc2026_standings (team_id, group_id, position, status) VALUES ('BRA', 'C', 1, 'qualified')"
        )
        conn.commit()

        alive, _ = get_alive_team_ids(conn)
        assert "BRA" in alive
        conn.close()


class TestBracketBasedOverridesStaleStandings:
    def test_r32_known_excludes_group_stage_eliminated_even_if_standings_stale(self):
        """Reproduces the real production bug: wc2026_standings marks every
        team 'active' (never advances past group stage), but the live
        bracket clearly knows only 32 teams qualified — alive_team_ids
        should reflect the bracket, not the stale 'active' standings."""
        conn = _make_db()
        groups = "ABCDEFGHIJKL"
        for g in groups:
            conn.execute("INSERT OR IGNORE INTO groups (id) VALUES (?)", (g,))
            for pos in range(1, 5):
                tid = f"{g}{pos}"
                conn.execute("INSERT OR IGNORE INTO teams (id, name) VALUES (?, ?)", (tid, tid))
                conn.execute(
                    "INSERT INTO group_teams (group_id, team_id, position) VALUES (?, ?, ?)",
                    (g, tid, pos),
                )
                # Stale standings — every team still 'active', never eliminated.
                conn.execute(
                    "INSERT INTO wc2026_standings (team_id, group_id, position, status) VALUES (?, ?, ?, 'active')",
                    (tid, g, pos),
                )
        # Play all 12 groups so results-based R32 fallback resolves.
        pairs = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
        for g in groups:
            teams = [f"{g}{p}" for p in range(1, 5)]
            for i, j in pairs:
                home, away = teams[i], teams[j]
                hg, ag = (2, 0) if i < j else (0, 2)
                conn.execute(
                    "INSERT INTO results (id, home_team_id, away_team_id, home_goals, away_goals, "
                    "match_date, source, is_wc) VALUES (?, ?, ?, ?, ?, '2026-06-15', 'api_football', 1)",
                    (f"{home}_{away}", home, away, hg, ag),
                )
        conn.commit()

        alive, warning = get_alive_team_ids(conn)

        # Group-stage eliminated teams (3rd/4th of each group, except best
        # 8 thirds) must NOT be in the alive set even though standings says 'active'.
        assert "A4" not in alive  # 4th place, never qualifies
        assert "A1" in alive      # 1st place, always qualifies
        conn.close()

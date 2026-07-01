"""Tests for get_key_player_pool — filters key players by real WC2026 squad."""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.features.squad_pool import get_key_player_pool


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    run_migrations(c)
    c.execute("INSERT OR IGNORE INTO teams (id, name, created_at) VALUES ('ARG', 'Argentina', '2026-01-01')")
    c.commit()
    yield c
    c.close()


def _add_sb_player(conn, team_id, player_name, match_id=1):
    conn.execute(
        """INSERT OR IGNORE INTO sb_matches
           (match_id, competition_id, season_id, competition_name, season_name,
            match_date, home_team_id, away_team_id, home_score, away_score,
            home_team_sb, away_team_sb)
           VALUES (?, 43, 106, 'WC', '2022', '2022-12-01', ?, 'FRA', 1, 0, ?, 'France')""",
        (match_id, team_id, team_id),
    )
    pid = f"{match_id}_{player_name}_{team_id}"[:16]
    conn.execute(
        """INSERT OR IGNORE INTO sb_player_stats
           (id, match_id, team_id, player_name, position, minutes_played, goals, xg, shots, key_passes)
           VALUES (?, ?, ?, ?, 'Forward', 90, 0, 0.5, 2, 1)""",
        (pid, match_id, team_id, player_name),
    )
    conn.commit()


def _add_squad_player(conn, team_id, player_name):
    conn.execute(
        "INSERT OR IGNORE INTO wc2026_squads (team_id, player_name) VALUES (?, ?)",
        (team_id, player_name),
    )
    conn.commit()


class TestNoSquadData:
    def test_falls_back_to_statsbomb_pool_with_warning(self, conn):
        _add_sb_player(conn, "ARG", "Messi")
        _add_sb_player(conn, "ARG", "Di Maria", match_id=2)

        pool = get_key_player_pool("ARG", conn)

        assert pool["squad_status"] == "missing"
        assert set(pool["players"]) == {"Messi", "Di Maria"}
        assert pool["warning"] is not None

    def test_empty_pool_when_no_statsbomb_data_either(self, conn):
        pool = get_key_player_pool("ARG", conn)
        assert pool["players"] == []
        assert pool["squad_status"] == "missing"


class TestSquadDataExcludesNonConvocados:
    def test_excludes_player_with_more_xg_but_not_in_squad(self, conn):
        _add_sb_player(conn, "ARG", "Messi", match_id=1)
        _add_sb_player(conn, "ARG", "OldPlayer", match_id=2)  # not in squad
        _add_squad_player(conn, "ARG", "Messi")

        pool = get_key_player_pool("ARG", conn)

        assert pool["squad_status"] == "confirmed"
        assert pool["players"] == ["Messi"]
        assert "OldPlayer" not in pool["players"]

    def test_partial_status_when_no_names_match(self, conn):
        _add_sb_player(conn, "ARG", "Messi")
        _add_squad_player(conn, "ARG", "Completely Different Name")

        pool = get_key_player_pool("ARG", conn)

        assert pool["squad_status"] == "partial"
        assert pool["players"] == []
        assert pool["warning"] is not None


class TestNameNormalization:
    def test_matches_accented_name_against_plain_squad_entry(self, conn):
        _add_sb_player(conn, "ARG", "Julián Álvarez")
        _add_squad_player(conn, "ARG", "julian alvarez")  # no accents, lowercase

        pool = get_key_player_pool("ARG", conn)

        assert pool["squad_status"] == "confirmed"
        assert pool["players"] == ["Julián Álvarez"]

    def test_matches_with_extra_whitespace(self, conn):
        _add_sb_player(conn, "ARG", "Lionel Messi")
        _add_squad_player(conn, "ARG", "  Lionel   Messi  ")

        pool = get_key_player_pool("ARG", conn)

        assert pool["squad_status"] == "confirmed"
        assert pool["players"] == ["Lionel Messi"]


class TestEmptyTables:
    def test_no_crash_when_tables_empty(self, conn):
        pool = get_key_player_pool("NONEXISTENT", conn)
        assert pool["players"] == []
        assert pool["squad_status"] == "missing"

"""Tests for BracketSimulator — live knockout bracket from real R32 qualifiers."""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from app.db.migrations import run_migrations
from app.services.simulation.bracket_simulator import (
    BracketSimulator,
    load_knockout_winners,
    load_r32_qualifiers,
    run_bracket_simulation,
)

_GROUPS = "ABCDEFGHIJKL"


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    return conn


def _seed_complete_groups(conn: sqlite3.Connection) -> None:
    """12 groups x 4 teams, all finished with clear point ordering per position."""
    for g in _GROUPS:
        conn.execute("INSERT OR IGNORE INTO groups (id) VALUES (?)", (g,))
        for pos in range(1, 5):
            tid = f"{g}{pos}"
            conn.execute("INSERT OR IGNORE INTO teams (id, name) VALUES (?, ?)", (tid, tid))
            conn.execute(
                "INSERT INTO group_teams (group_id, team_id, position) VALUES (?, ?, ?)",
                (g, tid, pos),
            )
            status = "qualified" if pos <= 2 else "eliminated"
            # Points/gd/gf tuned so the 3rd-placed team of group A is the best
            # third overall (used by test_best_thirds_selection).
            pts = (9 - pos) if g != "A" else (9 - pos + (1 if pos == 3 else 0))
            conn.execute(
                """
                INSERT INTO wc2026_standings
                    (team_id, group_id, position, points, goals_for, goals_against, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (tid, g, pos, pts, 10 - pos, pos, status),
            )
    conn.commit()


class TestLoadR32Qualifiers:
    def test_empty_standings_returns_empty(self):
        conn = _make_db()
        assert load_r32_qualifiers(conn) == {}
        conn.close()

    def test_incomplete_groups_returns_empty(self):
        """Only some groups finished — tournament hasn't reached R32 yet."""
        conn = _make_db()
        _seed_complete_groups(conn)
        # Revert group L back to 'active' (not finished)
        conn.execute("UPDATE wc2026_standings SET status = 'active' WHERE group_id = 'L'")
        conn.commit()
        assert load_r32_qualifiers(conn) == {}
        conn.close()

    def test_all_groups_complete_yields_32_qualifiers(self):
        conn = _make_db()
        _seed_complete_groups(conn)
        r32 = load_r32_qualifiers(conn)
        assert len(r32) == 32
        for g in _GROUPS:
            assert r32[f"1{g}"] == f"{g}1"
            assert r32[f"2{g}"] == f"{g}2"
        thirds = [v for k, v in r32.items() if k.startswith("T")]
        assert len(thirds) == 8
        conn.close()

    def test_best_third_selection_picks_highest_points(self):
        """Group A's 3rd place has a bonus point — must be among the 8 qualifying thirds."""
        conn = _make_db()
        _seed_complete_groups(conn)
        r32 = load_r32_qualifiers(conn)
        thirds = {v for k, v in r32.items() if k.startswith("T")}
        assert "A3" in thirds
        conn.close()


class TestLoadKnockoutWinners:
    def test_no_results_returns_empty(self):
        conn = _make_db()
        assert load_knockout_winners(conn, {"A1", "A2"}) == {}
        conn.close()

    def test_played_match_returns_winner(self):
        conn = _make_db()
        for tid in ("A1", "B1"):
            conn.execute("INSERT INTO teams (id, name) VALUES (?, ?)", (tid, tid))
        conn.execute(
            """
            INSERT INTO results
                (id, home_team_id, away_team_id, home_goals, away_goals,
                 match_date, is_wc)
            VALUES ('r1', 'A1', 'B1', 3, 1, '2026-07-02', 1)
            """
        )
        conn.commit()
        winners = load_knockout_winners(conn, {"A1", "B1"})
        assert winners[frozenset(("A1", "B1"))] == "A1"
        conn.close()

    def test_draw_is_skipped_as_unresolved(self):
        """Goals tied (likely penalties, not recorded) — treated as not-yet-played."""
        conn = _make_db()
        for tid in ("A1", "B1"):
            conn.execute("INSERT INTO teams (id, name) VALUES (?, ?)", (tid, tid))
        conn.execute(
            """
            INSERT INTO results
                (id, home_team_id, away_team_id, home_goals, away_goals,
                 match_date, is_wc)
            VALUES ('r1', 'A1', 'B1', 1, 1, '2026-07-02', 1)
            """
        )
        conn.commit()
        assert load_knockout_winners(conn, {"A1", "B1"}) == {}
        conn.close()

    def test_non_wc_result_ignored(self):
        """A friendly between the same two teams must not be treated as a knockout result."""
        conn = _make_db()
        for tid in ("A1", "B1"):
            conn.execute("INSERT INTO teams (id, name) VALUES (?, ?)", (tid, tid))
        conn.execute(
            """
            INSERT INTO results
                (id, home_team_id, away_team_id, home_goals, away_goals,
                 match_date, is_wc)
            VALUES ('r1', 'A1', 'B1', 3, 1, '2025-01-01', 0)
            """
        )
        conn.commit()
        assert load_knockout_winners(conn, {"A1", "B1"}) == {}
        conn.close()


class TestBracketSimulatorRespectsPlayedResults:
    def test_played_pair_never_resimulated(self):
        """A team that lost a real knockout match must never re-emerge as the
        winner of that exact match across many Monte Carlo iterations —
        the played result is authoritative, not just one possible outcome."""
        from app.services.prediction.baseline import BaselineModel

        conn = _make_db()
        _seed_complete_groups(conn)
        r32 = load_r32_qualifiers(conn)

        # Force A1 to lose to B2 in the real R32 pairing "1A" vs "2B".
        home, away = r32["1A"], r32["2B"]
        conn.execute(
            """
            INSERT INTO results
                (id, home_team_id, away_team_id, home_goals, away_goals,
                 match_date, is_wc)
            VALUES ('r1', ?, ?, 0, 2, '2026-07-02', 1)
            """,
            (home, away),
        )
        conn.commit()

        winners = load_knockout_winners(conn, set(r32.values()))
        assert winners[frozenset((home, away))] == away

        model = BaselineModel(conn)
        rng = np.random.default_rng(1)
        for _ in range(50):
            sim = BracketSimulator(model, r32, winners, rng)
            result = sim.simulate_once()
            # The loser of the real match must be marked eliminated at R32 in
            # every single iteration — never anything else for that match.
            assert result[home] == "round_of_32"
        conn.close()


class TestRunBracketSimulationPersists:
    def test_no_qualifiers_returns_empty_and_does_not_crash(self):
        conn = _make_db()
        summary = run_bracket_simulation(conn, "baseline", n_iterations=10)
        assert summary == {}
        conn.close()

    def test_persists_rows_for_all_32_qualifiers(self):
        conn = _make_db()
        _seed_complete_groups(conn)
        summary = run_bracket_simulation(conn, "baseline", n_iterations=50)
        assert len(summary) == 32

        rows = conn.execute(
            "SELECT DISTINCT team_id FROM bracket_simulations WHERE model_name = 'baseline'"
        ).fetchall()
        assert len(rows) == 32

    def test_real_loser_marked_eliminated_in_correct_round(self):
        conn = _make_db()
        _seed_complete_groups(conn)
        r32 = load_r32_qualifiers(conn)
        home, away = r32["1A"], r32["2B"]
        conn.execute(
            """
            INSERT INTO results
                (id, home_team_id, away_team_id, home_goals, away_goals,
                 match_date, is_wc)
            VALUES ('r1', ?, ?, 0, 2, '2026-07-02', 1)
            """,
            (home, away),
        )
        conn.commit()

        run_bracket_simulation(conn, "baseline", n_iterations=30)

        row = conn.execute(
            """
            SELECT advance_prob, is_eliminated FROM bracket_simulations
            WHERE model_name = 'baseline' AND team_id = ? AND round_name = 'round_of_32'
            """,
            (home,),
        ).fetchone()
        assert row["is_eliminated"] == 1
        assert row["advance_prob"] == pytest.approx(1.0)

        # The real loser must show advance_prob == 0 for every round beyond R32.
        for rnd in ("round_of_16", "quarterfinals", "semifinals", "final", "champion"):
            r = conn.execute(
                """
                SELECT advance_prob FROM bracket_simulations
                WHERE model_name = 'baseline' AND team_id = ? AND round_name = ?
                """,
                (home, rnd),
            ).fetchone()
            assert r["advance_prob"] == pytest.approx(0.0), f"{rnd}: expected 0.0, got {r['advance_prob']}"
        conn.close()

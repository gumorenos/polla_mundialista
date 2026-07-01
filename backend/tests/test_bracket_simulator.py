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
    def test_no_qualifiers_returns_no_r32_status(self):
        conn = _make_db()
        result = run_bracket_simulation(conn, "baseline", n_iterations=10)
        assert result["status"] == "no_r32"
        assert result["teams"] == {}
        assert result["run_id"] is not None
        assert "clasificados" in result["message"]

        run_row = conn.execute(
            "SELECT status, error_message FROM bracket_runs WHERE id = ?", (result["run_id"],)
        ).fetchone()
        assert run_row["status"] == "no_r32"
        assert run_row["error_message"] == result["message"]
        conn.close()

    def test_persists_rows_for_all_32_qualifiers(self):
        conn = _make_db()
        _seed_complete_groups(conn)
        result = run_bracket_simulation(conn, "baseline", n_iterations=50)
        assert result["status"] == "completed"
        assert len(result["teams"]) == 32

        rows = conn.execute(
            "SELECT DISTINCT team_id FROM bracket_simulation_results WHERE bracket_run_id = ?",
            (result["run_id"],),
        ).fetchall()
        assert len(rows) == 32

        run_row = conn.execute(
            "SELECT status, r32_source FROM bracket_runs WHERE id = ?", (result["run_id"],)
        ).fetchone()
        assert run_row["status"] == "completed"
        assert run_row["r32_source"] == "wc2026_standings"

    def test_two_runs_of_same_model_produce_distinct_run_ids_and_keep_history(self):
        conn = _make_db()
        _seed_complete_groups(conn)
        r1 = run_bracket_simulation(conn, "baseline", n_iterations=20)
        r2 = run_bracket_simulation(conn, "baseline", n_iterations=20)
        assert r1["run_id"] != r2["run_id"]

        run_count = conn.execute(
            "SELECT COUNT(*) c FROM bracket_runs WHERE model_name = 'baseline'"
        ).fetchone()["c"]
        assert run_count == 2

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

        result = run_bracket_simulation(conn, "baseline", n_iterations=30)
        run_id = result["run_id"]

        row = conn.execute(
            """
            SELECT advance_prob, is_eliminated FROM bracket_simulation_results
            WHERE bracket_run_id = ? AND team_id = ? AND round_name = 'round_of_32'
            """,
            (run_id, home),
        ).fetchone()
        assert row["is_eliminated"] == 1
        assert row["advance_prob"] == pytest.approx(1.0)

        # The real loser must show advance_prob == 0 for every round beyond R32.
        for rnd in ("round_of_16", "quarterfinals", "semifinals", "final", "champion"):
            r = conn.execute(
                """
                SELECT advance_prob FROM bracket_simulation_results
                WHERE bracket_run_id = ? AND team_id = ? AND round_name = ?
                """,
                (run_id, home, rnd),
            ).fetchone()
            assert r["advance_prob"] == pytest.approx(0.0), f"{rnd}: expected 0.0, got {r['advance_prob']}"
        conn.close()


class TestGetLatestBracketView:
    def test_no_run_ever_attempted(self):
        from app.services.simulation.bracket_simulator import get_latest_bracket_view
        conn = _make_db()
        view = get_latest_bracket_view(conn, "baseline")
        assert view["status"] is None
        assert view["run_id"] is None
        assert view["rounds"] == {}
        conn.close()

    def test_no_r32_surfaces_clear_message(self):
        from app.services.simulation.bracket_simulator import get_latest_bracket_view
        conn = _make_db()
        run_bracket_simulation(conn, "baseline", n_iterations=5)
        view = get_latest_bracket_view(conn, "baseline")
        assert view["status"] == "no_r32"
        assert "clasificados" in view["message"]
        conn.close()

    def test_completed_run_returns_rounds_and_meta(self):
        from app.services.simulation.bracket_simulator import get_latest_bracket_view
        conn = _make_db()
        _seed_complete_groups(conn)
        result = run_bracket_simulation(conn, "baseline", n_iterations=20)

        view = get_latest_bracket_view(conn, "baseline")
        assert view["status"] == "completed"
        assert view["run_id"] == result["run_id"]
        assert "round_of_32" in view["rounds"]
        assert view["meta"]["iterations"] == 20
        conn.close()


class TestR32FallbackFromResults:
    """wc2026_standings can be stale/incomplete (e.g. the fixtures<->results
    join used by calculate_standings_from_results silently under-matching
    real games) — load_r32_qualifiers must still resolve R32 directly from
    `results` when that happens."""

    def _seed_groups_only(self, conn: sqlite3.Connection) -> None:
        """group_teams populated, but wc2026_standings left EMPTY/stale —
        simulates the real production bug found post-deploy."""
        for g in _GROUPS:
            conn.execute("INSERT OR IGNORE INTO groups (id) VALUES (?)", (g,))
            for pos in range(1, 5):
                tid = f"{g}{pos}"
                conn.execute("INSERT OR IGNORE INTO teams (id, name) VALUES (?, ?)", (tid, tid))
                conn.execute(
                    "INSERT INTO group_teams (group_id, team_id, position) VALUES (?, ?, ?)",
                    (g, tid, pos),
                )
                # standings row exists but status is never advanced past 'active'
                conn.execute(
                    "INSERT INTO wc2026_standings (team_id, group_id, position, status) VALUES (?, ?, ?, 'active')",
                    (tid, g, pos),
                )
        conn.commit()

    def _play_group(self, conn, teams: list[str], winner_pts: dict[str, int]) -> None:
        """Insert 6 round-robin results for a 4-team group directly into
        `results`, with scores chosen so final points match winner_pts."""
        # Simple deterministic scheme: team i beats team j (i<j) with a
        # scoreline that gives team i 3 pts, unless winner_pts overrides —
        # for this test we just need a clean, unambiguous 1-2-3-4 order.
        pairs = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
        for i, j in pairs:
            home, away = teams[i], teams[j]
            # Lower index always wins by rank order 0>1>2>3.
            hg, ag = (2, 0) if i < j else (0, 2)
            conn.execute(
                "INSERT INTO results (id, home_team_id, away_team_id, home_goals, away_goals, "
                "match_date, source, is_wc) VALUES (?, ?, ?, ?, ?, '2026-06-15', 'api_football', 1)",
                (f"{home}_{away}_{i}{j}", home, away, hg, ag),
            )
        conn.commit()

    def test_falls_back_to_results_when_standings_stale(self):
        conn = _make_db()
        self._seed_groups_only(conn)
        for g in _GROUPS:
            teams = [f"{g}{p}" for p in range(1, 5)]
            self._play_group(conn, teams, {})

        r32 = load_r32_qualifiers(conn)
        assert len(r32) == 32
        for g in _GROUPS:
            assert r32[f"1{g}"] == f"{g}1"
            assert r32[f"2{g}"] == f"{g}2"
        conn.close()

    def test_no_fallback_when_groups_incomplete(self):
        conn = _make_db()
        self._seed_groups_only(conn)
        for g in _GROUPS:
            teams = [f"{g}{p}" for p in range(1, 5)]
            self._play_group(conn, teams, {})
        # Group L never played — group_teams incomplete data for fallback.
        conn.execute("DELETE FROM results WHERE home_team_id LIKE 'L%' OR away_team_id LIKE 'L%'")
        conn.commit()

        assert load_r32_qualifiers(conn) == {}
        conn.close()

    def test_standings_source_preferred_when_available(self):
        """If wc2026_standings IS complete and correct, it's used — the
        results fallback is only a safety net, not the primary path."""
        conn = _make_db()
        _seed_complete_groups(conn)  # standings fully populated + qualified
        r32 = load_r32_qualifiers(conn)
        assert len(r32) == 32
        conn.close()

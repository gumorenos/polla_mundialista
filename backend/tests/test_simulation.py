"""Tests for WC2026Bracket and Monte Carlo simulation."""

from __future__ import annotations

import sqlite3
import uuid

import numpy as np
import pytest

from app.db.migrations import run_migrations
from app.services.simulation.constants import GROUPS_2026


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db() -> sqlite3.Connection:
    """Minimal in-memory DB with migrations applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    return conn


def _seed_teams(conn: sqlite3.Connection) -> None:
    """Insert all 48 WC2026 teams (needed for FK constraints)."""
    all_ids = [tid for tids in GROUPS_2026.values() for tid in tids]
    for tid in all_ids:
        conn.execute(
            "INSERT OR IGNORE INTO teams (id, name) VALUES (?, ?)", (tid, tid)
        )
    conn.commit()


def _make_baseline_model(conn: sqlite3.Connection):
    from app.services.prediction.baseline import BaselineModel
    return BaselineModel(conn)


def _make_bracket(model, rng=None) -> "WC2026Bracket":
    from app.services.simulation.wc2026_bracket import WC2026Bracket
    rng = rng or np.random.default_rng(42)
    return WC2026Bracket(model, {k: list(v) for k, v in GROUPS_2026.items()}, rng)


# ---------------------------------------------------------------------------
# Module-scoped fixture: DB with teams, run a 100-iteration simulation
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def simulation_result():
    """Run 100-iteration Monte Carlo with baseline model and return metadata."""
    from app.services.simulation.monte_carlo import run_monte_carlo

    conn = _make_db()
    _seed_teams(conn)

    run_id = run_monte_carlo(
        model_name="baseline",
        conn=conn,
        iterations=100,
        seed=42,
    )
    yield {"conn": conn, "run_id": run_id}
    conn.close()


# ---------------------------------------------------------------------------
# 1. sum(win_tournament) across all teams ≈ 100% (±2%)
# ---------------------------------------------------------------------------

class TestWinTournamentSum:
    def test_win_probabilities_sum_to_100_pct(self, simulation_result):
        conn   = simulation_result["conn"]
        run_id = simulation_result["run_id"]

        rows = conn.execute(
            "SELECT win_tournament FROM simulation_team_results "
            "WHERE simulation_run_id = ?",
            (run_id,),
        ).fetchall()

        total = sum(r["win_tournament"] for r in rows)
        assert abs(total - 1.0) <= 0.02, (
            f"Sum of win_tournament = {total:.4f}, expected ≈ 1.0 (±0.02)"
        )


# ---------------------------------------------------------------------------
# 2. Exactly 32 teams classify to R32
# ---------------------------------------------------------------------------

class TestGroupStageClassification:
    def test_exactly_32_teams_classify(self):
        conn = _make_db()
        _seed_teams(conn)
        model   = _make_baseline_model(conn)
        bracket = _make_bracket(model)

        classified = bracket.play_group_stage()

        assert len(classified) == 32, (
            f"Expected 32 classified teams, got {len(classified)}: {list(classified.keys())}"
        )
        conn.close()

    def test_each_group_contributes_at_least_2(self):
        conn = _make_db()
        _seed_teams(conn)
        model   = _make_baseline_model(conn)
        bracket = _make_bracket(model)

        classified = bracket.play_group_stage()

        for letter in GROUPS_2026:
            assert f"1{letter}" in classified, f"Missing group winner 1{letter}"
            assert f"2{letter}" in classified, f"Missing group runner-up 2{letter}"
        conn.close()

    def test_eight_best_thirds_qualify(self):
        conn = _make_db()
        _seed_teams(conn)
        model   = _make_baseline_model(conn)
        bracket = _make_bracket(model)

        classified = bracket.play_group_stage()

        thirds = [k for k in classified if k.startswith("T")]
        assert len(thirds) == 8, f"Expected 8 best thirds, got {len(thirds)}: {thirds}"
        conn.close()


# ---------------------------------------------------------------------------
# 3. Champion is always one of the 48 WC2026 teams
# ---------------------------------------------------------------------------

class TestChampionValidity:
    def test_champion_is_one_of_48_teams(self):
        conn = _make_db()
        _seed_teams(conn)
        model = _make_baseline_model(conn)
        all_team_ids = {tid for tids in GROUPS_2026.values() for tid in tids}

        for seed in range(5):
            bracket = _make_bracket(model, np.random.default_rng(seed))
            result  = bracket.run()
            assert result["champion"] in all_team_ids, (
                f"Champion '{result['champion']}' is not in the 48 WC2026 teams"
            )
        conn.close()

    def test_full_run_produces_single_champion(self):
        conn = _make_db()
        _seed_teams(conn)
        model   = _make_baseline_model(conn)
        bracket = _make_bracket(model)
        result  = bracket.run()

        assert result["champion"] is not None
        assert result["runner_up"] is not None
        assert result["champion"] != result["runner_up"]
        conn.close()


# ---------------------------------------------------------------------------
# 4. simulation_run has status 'completed' after run_monte_carlo
# ---------------------------------------------------------------------------

class TestSimulationRunStatus:
    def test_status_is_completed(self, simulation_result):
        conn   = simulation_result["conn"]
        run_id = simulation_result["run_id"]

        row = conn.execute(
            "SELECT status FROM simulation_runs WHERE id = ?", (run_id,)
        ).fetchone()

        assert row is not None, "simulation_run record not found"
        assert row["status"] == "completed", (
            f"Expected status='completed', got '{row['status']}'"
        )

    def test_started_at_and_finished_at_populated(self, simulation_result):
        conn   = simulation_result["conn"]
        run_id = simulation_result["run_id"]

        row = conn.execute(
            "SELECT started_at, finished_at FROM simulation_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        assert row["started_at"] is not None
        assert row["finished_at"] is not None


# ---------------------------------------------------------------------------
# 5. progress reaches 1.0 at the end (via run_simulation_task)
# ---------------------------------------------------------------------------

class TestProgress:
    def test_progress_reaches_1_0(self):
        from app.db.repositories.jobs import JobRepository
        from app.workers.tasks import run_simulation_task

        conn = _make_db()
        _seed_teams(conn)

        # Pre-create a job record that the task will update
        job_repo = JobRepository(conn)
        job_id   = job_repo.create({"job_type": "simulation", "status": "enqueued"})
        conn.commit()

        result = run_simulation_task(
            model_name="baseline",
            iterations=20,
            seed=99,
            job_id=job_id,
            _conn=conn,
        )

        assert result["progress"] == pytest.approx(1.0)

        job_row = conn.execute(
            "SELECT progress, status FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        assert job_row["progress"] == pytest.approx(1.0)
        assert job_row["status"] == "completed"
        conn.close()


# ---------------------------------------------------------------------------
# TestLoadGroupsFromDB
# ---------------------------------------------------------------------------

class TestLoadGroupsFromDB:
    def test_groups_loaded_from_db_not_hardcoded(self):
        """When group_teams has data, _load_groups must return DB rows, not fallback."""
        from app.services.simulation.monte_carlo import _load_groups

        conn = _make_db()
        conn.execute("INSERT INTO groups (id, tournament) VALUES ('G_TEST', 'WC2026')")
        conn.execute("INSERT INTO teams (id, name) VALUES ('TST1', 'Test Team One')")
        conn.execute(
            "INSERT INTO group_teams (group_id, team_id, position) VALUES ('G_TEST', 'TST1', 1)"
        )
        conn.commit()

        groups = _load_groups(conn)

        assert "G_TEST" in groups, "DB groups should override GROUPS_2026 fallback"
        assert "TST1" in groups["G_TEST"]
        conn.close()

    def test_empty_group_teams_uses_fallback(self):
        """Empty group_teams table → GROUPS_2026 fallback is used."""
        from app.services.simulation.monte_carlo import _load_groups
        from app.services.simulation.constants import GROUPS_2026

        conn = _make_db()
        groups = _load_groups(conn)

        assert groups == {k: list(v) for k, v in GROUPS_2026.items()}
        conn.close()


# ---------------------------------------------------------------------------
# 7. FK robustness: team not in teams table must not crash simulation
# ---------------------------------------------------------------------------

class TestFKRobustness:
    def test_unknown_team_skipped_without_crash(self):
        """run_monte_carlo must complete successfully even when group_teams
        references a team_id that is absent from the teams table.
        The missing team is warned and skipped; the run ends as 'completed'."""
        from app.services.simulation.monte_carlo import run_monte_carlo

        conn = _make_db()

        # Insert one group with a dangling team reference to emulate legacy or
        # externally corrupted data. Foreign keys are re-enabled before running.
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("INSERT INTO groups (id, tournament) VALUES ('G_FK', 'WC2026')")
        conn.execute("INSERT INTO teams (id, name) VALUES ('REAL1', 'Real Team')")
        conn.execute("INSERT INTO teams (id, name) VALUES ('REAL2', 'Real Team 2')")
        conn.execute("INSERT INTO teams (id, name) VALUES ('REAL3', 'Real Team 3')")
        # GHOST is intentionally NOT in teams — should be skipped, not crash
        for pos, tid in enumerate(["REAL1", "REAL2", "REAL3", "GHOST"], start=1):
            conn.execute(
                "INSERT INTO group_teams (group_id, team_id, position) VALUES ('G_FK', ?, ?)",
                (tid, pos),
            )
        conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")

        # Run a minimal simulation — must not raise
        run_id = run_monte_carlo(
            model_name="baseline",
            conn=conn,
            iterations=10,
            seed=7,
        )

        row = conn.execute(
            "SELECT status FROM simulation_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert row is not None
        assert row["status"] == "completed", f"Expected 'completed', got '{row['status']}'"
        ghost_result = conn.execute(
            "SELECT 1 FROM simulation_team_results WHERE simulation_run_id = ? AND team_id = 'GHOST'",
            (run_id,),
        ).fetchone()
        assert ghost_result is None
        conn.close()

    def test_missing_team_in_db_produces_warning(self, caplog):
        """When group_teams is empty (GROUPS_2026 fallback used) but teams table only
        has a subset of teams, run_monte_carlo logs a WARNING about skipped teams."""
        import logging
        from app.services.simulation.monte_carlo import run_monte_carlo
        from app.services.simulation.constants import GROUPS_2026

        conn = _make_db()

        # Seed only ONE team from GROUPS_2026 — all others will be skipped
        first_tid = next(iter(next(iter(GROUPS_2026.values()))))
        conn.execute("INSERT OR IGNORE INTO teams (id, name) VALUES (?, ?)", (first_tid, first_tid))
        conn.commit()

        # group_teams is empty → _load_groups falls back to GROUPS_2026 (all 48 teams)
        # teams table only has 1 → 47 will be skipped with WARNING
        with caplog.at_level(logging.WARNING, logger="app.services.simulation.monte_carlo"):
            run_monte_carlo(model_name="baseline", conn=conn, iterations=5, seed=3)

        skipped_msgs = [r.message for r in caplog.records if "not in teams table" in r.message]
        assert skipped_msgs, "Expected at least one WARNING about team not in teams table"
        conn.close()

    def test_no_persisted_team_results_fails_run(self):
        """A simulation must not be marked completed if no team result rows are saved."""
        from app.services.simulation.monte_carlo import run_monte_carlo

        conn = _make_db()

        with pytest.raises(RuntimeError, match="no persisted team results"):
            run_monte_carlo(model_name="baseline", conn=conn, iterations=1, seed=11)

        row = conn.execute(
            "SELECT status, error_message FROM simulation_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row["status"] == "failed"
        assert "no persisted team results" in row["error_message"]
        conn.close()

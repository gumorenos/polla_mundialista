"""Tests for scripts/mark_invalid_simulation_runs.py — find_invalid_runs and
mark_invalid must never touch valid runs, and dry-run must never write."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from app.db.migrations import run_migrations
from app.db.repositories.simulations import SimulationRepository
from mark_invalid_simulation_runs import ERROR_MESSAGE, find_invalid_runs, mark_invalid


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    conn.execute("INSERT OR IGNORE INTO teams (id, name) VALUES ('ARG', 'Argentina')")
    conn.commit()
    return conn


def _valid_row(**overrides) -> dict:
    row = {
        "win_group": 0.3, "qualify": 0.9,
        "reach_round_of_32": 0.9, "reach_round_of_16": 0.5,
        "reach_quarter_final": 0.3, "reach_semi_final": 0.15,
        "reach_final": 0.08, "win_tournament": 0.04,
    }
    row.update(overrides)
    return row


def _insert_run_with_result(conn, model_name="elo", **overrides) -> str:
    run_id = SimulationRepository(conn).create_run({"model_name": model_name, "status": "completed"})
    SimulationRepository(conn).insert_team_result({
        "simulation_run_id": run_id, "team_id": "ARG", **_valid_row(**overrides),
        "expected_group_points": None,
    })
    conn.commit()
    return run_id


class TestFindInvalidRuns:
    def test_finds_only_invalid_runs(self):
        conn = _make_db()
        valid_id = _insert_run_with_result(conn, model_name="elo")
        invalid_id = _insert_run_with_result(conn, model_name="poisson", reach_round_of_32=1.3)

        found = find_invalid_runs(conn)
        found_ids = {r["run_id"] for r in found}

        assert invalid_id in found_ids
        assert valid_id not in found_ids

    def test_empty_when_all_valid(self):
        conn = _make_db()
        _insert_run_with_result(conn)
        assert find_invalid_runs(conn) == []

    def test_does_not_modify_db(self):
        """find_invalid_runs is read-only — a subsequent query must show
        the run still 'completed', not touched."""
        conn = _make_db()
        run_id = _insert_run_with_result(conn, reach_round_of_32=1.3)
        find_invalid_runs(conn)

        status = conn.execute(
            "SELECT status FROM simulation_runs WHERE id = ?", (run_id,)
        ).fetchone()["status"]
        assert status == "completed"


class TestMarkInvalid:
    def test_marks_only_given_runs(self):
        conn = _make_db()
        valid_id = _insert_run_with_result(conn, model_name="elo")
        invalid_id = _insert_run_with_result(conn, model_name="poisson", reach_round_of_32=1.3)

        n = mark_invalid(conn, [invalid_id])
        assert n == 1

        invalid_status = conn.execute(
            "SELECT status, error_message FROM simulation_runs WHERE id = ?", (invalid_id,)
        ).fetchone()
        assert invalid_status["status"] == "invalid"
        assert invalid_status["error_message"] == ERROR_MESSAGE

        valid_status = conn.execute(
            "SELECT status FROM simulation_runs WHERE id = ?", (valid_id,)
        ).fetchone()
        assert valid_status["status"] == "completed"

    def test_invalidated_run_excluded_from_latest_valid(self):
        from app.services.simulation.validation import get_latest_valid_run

        conn = _make_db()
        # Only run available for this model, and it's invalid.
        invalid_id = _insert_run_with_result(conn, model_name="elo", reach_round_of_32=1.3)
        mark_invalid(conn, [invalid_id])

        assert get_latest_valid_run(conn, "elo") is None

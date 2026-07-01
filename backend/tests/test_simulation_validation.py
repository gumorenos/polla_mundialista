"""Tests for app.services.simulation.validation and the guardrails that
prevent invalid simulation_runs from being served as 'latest' or consumed
by consensus."""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.db.repositories.jobs import JobRepository
from app.db.repositories.simulations import SimulationRepository
from app.services.simulation.validation import (
    get_latest_valid_run,
    is_run_valid,
    validate_simulation_run,
    validate_team_result,
)


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    conn.execute("INSERT OR IGNORE INTO teams (id, name) VALUES ('ARG', 'Argentina')")
    conn.execute("INSERT OR IGNORE INTO teams (id, name) VALUES ('BRA', 'Brasil')")
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


def _insert_run(conn, model_name="elo", status="completed") -> str:
    run_id = SimulationRepository(conn).create_run({"model_name": model_name, "status": status})
    conn.commit()
    return run_id


def _insert_result(conn, run_id, team_id, **overrides):
    row = _valid_row(**overrides)
    SimulationRepository(conn).insert_team_result({
        "simulation_run_id": run_id, "team_id": team_id, **row,
        "expected_group_points": None,
    })
    conn.commit()


class TestValidateTeamResult:
    def test_valid_row_has_no_errors(self):
        assert validate_team_result(_valid_row()) == []

    def test_out_of_range_flagged(self):
        errors = validate_team_result(_valid_row(reach_round_of_32=1.2))
        assert any("fuera de rango" in e for e in errors)

    def test_monotonicity_violation_flagged(self):
        # reach_semi_final > reach_quarter_final
        errors = validate_team_result(_valid_row(reach_semi_final=0.5, reach_quarter_final=0.3))
        assert any("monotonicidad" in e for e in errors)

    def test_reach_round_of_32_must_equal_qualify(self):
        errors = validate_team_result(_valid_row(reach_round_of_32=0.9, qualify=0.5))
        assert any("!= qualify" in e for e in errors)

    def test_within_tolerance_is_ok(self):
        errors = validate_team_result(_valid_row(reach_round_of_32=0.90005, qualify=0.9))
        assert errors == []


class TestValidateSimulationRun:
    def test_valid_run_reports_no_violations(self):
        conn = _make_db()
        run_id = _insert_run(conn)
        _insert_result(conn, run_id, "ARG")
        _insert_result(conn, run_id, "BRA")

        result = validate_simulation_run(conn, run_id)
        assert result["valid"] is True
        assert result["violations"] == []
        assert result["checked"] == 2

    def test_invalid_run_reports_team_and_errors(self):
        conn = _make_db()
        run_id = _insert_run(conn)
        _insert_result(conn, run_id, "ARG", reach_round_of_32=1.2)
        _insert_result(conn, run_id, "BRA")

        result = validate_simulation_run(conn, run_id)
        assert result["valid"] is False
        assert len(result["violations"]) == 1
        assert result["violations"][0]["team_id"] == "ARG"
        assert result["violations"][0]["team_name"] == "Argentina"

    def test_run_with_no_results_is_invalid(self):
        conn = _make_db()
        run_id = _insert_run(conn)
        result = validate_simulation_run(conn, run_id)
        assert result["valid"] is False
        assert result["checked"] == 0


class TestIsRunValid:
    def test_true_for_valid_run(self):
        conn = _make_db()
        run_id = _insert_run(conn)
        _insert_result(conn, run_id, "ARG")
        assert is_run_valid(conn, run_id) is True

    def test_false_for_invalid_run(self):
        conn = _make_db()
        run_id = _insert_run(conn)
        _insert_result(conn, run_id, "ARG", reach_round_of_32=1.3)
        assert is_run_valid(conn, run_id) is False


class TestGetLatestValidRun:
    def test_skips_invalid_latest_and_returns_older_valid(self):
        conn = _make_db()
        old_valid = _insert_run(conn)
        _insert_result(conn, old_valid, "ARG")
        SimulationRepository(conn).update_run_status(old_valid, "completed", finished_at="2026-06-29T00:00:00Z")

        new_invalid = _insert_run(conn)
        _insert_result(conn, new_invalid, "ARG", reach_round_of_32=1.25)
        SimulationRepository(conn).update_run_status(new_invalid, "completed", finished_at="2026-06-30T00:00:00Z")
        conn.commit()

        run = get_latest_valid_run(conn, "elo")
        assert run is not None
        assert run["id"] == old_valid

    def test_none_when_all_runs_invalid(self):
        conn = _make_db()
        run_id = _insert_run(conn)
        _insert_result(conn, run_id, "ARG", reach_round_of_32=1.3)
        SimulationRepository(conn).update_run_status(run_id, "completed", finished_at="2026-06-30T00:00:00Z")
        conn.commit()

        assert get_latest_valid_run(conn, "elo") is None

    def test_none_when_no_runs_at_all(self):
        conn = _make_db()
        assert get_latest_valid_run(conn, "elo") is None


class TestConsensusSkipsInvalidRuns:
    def test_consensus_skips_model_with_only_invalid_runs(self):
        from app.services.prediction.consensus import compute_consensus_from_results

        conn = _make_db()

        # elo: valid
        elo_run = _insert_run(conn, model_name="elo")
        _insert_result(conn, elo_run, "ARG", win_tournament=0.04)
        SimulationRepository(conn).update_run_status(elo_run, "completed", finished_at="2026-06-30T00:00:00Z")

        # poisson: invalid (only run available)
        poisson_run = _insert_run(conn, model_name="poisson")
        _insert_result(conn, poisson_run, "ARG", reach_round_of_32=1.3)
        SimulationRepository(conn).update_run_status(poisson_run, "completed", finished_at="2026-06-30T00:00:00Z")

        # poisson_context: valid
        pc_run = _insert_run(conn, model_name="poisson_context")
        _insert_result(conn, pc_run, "ARG", win_tournament=0.05)
        SimulationRepository(conn).update_run_status(pc_run, "completed", finished_at="2026-06-30T00:00:00Z")
        conn.commit()

        result = compute_consensus_from_results(conn)
        assert "ARG" in result
        assert "poisson" not in result["ARG"]["models_used"]
        assert "elo" in result["ARG"]["models_used"]
        assert "poisson_context" in result["ARG"]["models_used"]

    def test_consensus_empty_when_all_models_invalid(self):
        from app.services.prediction.consensus import compute_consensus_from_results

        conn = _make_db()
        run_id = _insert_run(conn, model_name="elo")
        _insert_result(conn, run_id, "ARG", reach_round_of_32=1.3)
        SimulationRepository(conn).update_run_status(run_id, "completed", finished_at="2026-06-30T00:00:00Z")
        conn.commit()

        assert compute_consensus_from_results(conn) == {}

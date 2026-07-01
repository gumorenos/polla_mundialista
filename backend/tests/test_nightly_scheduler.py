"""Tests for scheduler/jobs.py nightly orchestration: daily_update gate,
duplicate prevention, and the 'skip with clear reason' contract."""

from __future__ import annotations

import sqlite3
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.db.migrations import run_migrations
from app.db.repositories.jobs import JobRepository


def _bootstrap_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.commit()
    conn.close()


def _query(path: str, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def _insert_job(path: str, job_type: str, status: str) -> None:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    JobRepository(conn).create({"job_type": job_type, "status": status})
    conn.commit()
    conn.close()


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "nightly.db")
    _bootstrap_db(path)
    monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", path)
    return path


@pytest.fixture()
def _mock_rq():
    # jobs.py does `from redis import Redis` / `from rq import Queue` locally
    # inside each function — patch the source modules so those fresh
    # per-call imports resolve to the mocks.
    with patch("redis.Redis") as mock_redis_cls, \
         patch("rq.Queue") as mock_queue_cls:
        mock_redis_cls.from_url.return_value = MagicMock()
        mock_queue = MagicMock()
        mock_queue.enqueue.return_value = MagicMock(id=f"rq-{uuid.uuid4().hex[:8]}")
        mock_queue_cls.return_value = mock_queue
        yield mock_queue


class TestJobExistsToday:
    def test_false_when_no_job(self, db_path):
        from app.db.connection import get_connection
        from app.scheduler.jobs import _job_exists_today
        conn = get_connection()
        assert _job_exists_today(conn, "daily_update") is False
        conn.close()

    def test_true_when_job_exists(self, db_path):
        from app.db.connection import get_connection
        from app.scheduler.jobs import _job_exists_today
        _insert_job(db_path, "daily_update", "completed")
        conn = get_connection()
        assert _job_exists_today(conn, "daily_update") is True
        conn.close()

    def test_status_filter_excludes_non_matching(self, db_path):
        from app.db.connection import get_connection
        from app.scheduler.jobs import _job_exists_today
        _insert_job(db_path, "daily_update", "failed")
        conn = get_connection()
        assert _job_exists_today(conn, "daily_update", ("enqueued", "running", "started")) is False
        conn.close()


class TestNightlySkipsWithoutDailyUpdate:
    def test_skips_when_no_daily_update_today(self, db_path):
        """If daily_update hasn't completed today, nightly dispatch must skip
        with a clear reason — not fail technically, not silently do nothing."""
        from app.scheduler.jobs import enqueue_nightly_update_and_simulations
        enqueue_nightly_update_and_simulations()

        rows = _query(db_path, "SELECT status, error_message FROM jobs WHERE job_type = 'nightly_update_and_simulations'")
        assert len(rows) == 1
        assert rows[0]["status"] == "skipped"
        assert "daily_update" in rows[0]["error_message"]

    def test_skips_when_daily_update_failed(self, db_path):
        _insert_job(db_path, "daily_update", "failed")

        from app.scheduler.jobs import enqueue_nightly_update_and_simulations
        enqueue_nightly_update_and_simulations()

        rows = _query(db_path, "SELECT status FROM jobs WHERE job_type = 'nightly_update_and_simulations'")
        assert rows[0]["status"] == "skipped"


class TestNightlyDispatchesWhenDailyUpdateOk:
    def test_dispatches_bracket_and_full_models(self, db_path, monkeypatch, _mock_rq):
        monkeypatch.setattr("app.core.config.settings.NIGHTLY_SIMULATION_MODELS", ["elo", "consensus"])
        monkeypatch.setattr("app.core.config.settings.NIGHTLY_BRACKET_MODELS", ["elo"])
        _insert_job(db_path, "daily_update", "completed")

        from app.scheduler.jobs import enqueue_nightly_update_and_simulations
        enqueue_nightly_update_and_simulations()

        job_types = {r["job_type"] for r in _query(db_path, "SELECT job_type FROM jobs")}
        assert "simulation_bracket_elo" in job_types
        assert "simulation_full_elo" in job_types
        assert "simulation_full_consensus" in job_types

        nightly = _query(db_path, "SELECT status FROM jobs WHERE job_type = 'nightly_update_and_simulations'")
        assert nightly[0]["status"] == "completed"

    def test_consensus_dispatched_after_base_models(self, db_path, monkeypatch, _mock_rq):
        """Consensus must be enqueued strictly after base models so FIFO on the
        single 'long' worker guarantees it aggregates fresh results."""
        monkeypatch.setattr("app.core.config.settings.NIGHTLY_SIMULATION_MODELS", ["elo", "poisson", "consensus"])
        monkeypatch.setattr("app.core.config.settings.NIGHTLY_BRACKET_MODELS", [])
        _insert_job(db_path, "daily_update", "completed")

        from app.scheduler.jobs import enqueue_nightly_update_and_simulations
        enqueue_nightly_update_and_simulations()

        calls = [c.args[1] for c in _mock_rq.enqueue.call_args_list]  # model_name is 2nd positional arg
        assert calls.index("consensus") > calls.index("elo")
        assert calls.index("consensus") > calls.index("poisson")

    def test_does_not_duplicate_active_job_same_day(self, db_path, monkeypatch, _mock_rq):
        """If a simulation_full_elo job is already enqueued today, nightly
        dispatch must not create a second one for the same model."""
        monkeypatch.setattr("app.core.config.settings.NIGHTLY_SIMULATION_MODELS", ["elo"])
        monkeypatch.setattr("app.core.config.settings.NIGHTLY_BRACKET_MODELS", [])
        _insert_job(db_path, "daily_update", "completed")
        _insert_job(db_path, "simulation_full_elo", "running")

        from app.scheduler.jobs import enqueue_nightly_update_and_simulations
        enqueue_nightly_update_and_simulations()

        count = _query(db_path, "SELECT COUNT(*) c FROM jobs WHERE job_type = 'simulation_full_elo'")[0]["c"]
        assert count == 1

    def test_does_not_dispatch_twice_same_day(self, db_path, monkeypatch, _mock_rq):
        """A second call the same day (e.g. misfire retry) must not re-dispatch."""
        monkeypatch.setattr("app.core.config.settings.NIGHTLY_SIMULATION_MODELS", ["elo"])
        monkeypatch.setattr("app.core.config.settings.NIGHTLY_BRACKET_MODELS", [])
        _insert_job(db_path, "daily_update", "completed")

        from app.scheduler.jobs import enqueue_nightly_update_and_simulations
        enqueue_nightly_update_and_simulations()
        enqueue_nightly_update_and_simulations()

        count = _query(db_path, "SELECT COUNT(*) c FROM jobs WHERE job_type = 'nightly_update_and_simulations'")[0]["c"]
        assert count == 1

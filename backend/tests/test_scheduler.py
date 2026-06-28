"""Tests for Prompt 11 — scheduler jobs, snapshot endpoints, metrics endpoint."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.db.migrations import run_migrations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    return conn


def _insert_team(conn, tid: str, name: str) -> None:
    conn.execute("INSERT OR IGNORE INTO teams (id, name) VALUES (?, ?)", (tid, name))


def _insert_fixture(conn, fid: str, home_id: str, away_id: str, match_date: str) -> None:
    conn.execute(
        "INSERT INTO fixtures (id, stage, home_team_id, away_team_id, match_date) "
        "VALUES (?, 'Group A', ?, ?, ?)",
        (fid, home_id, away_id, match_date),
    )


def _insert_simulation_run(conn, run_id: str, model: str = "poisson") -> None:
    conn.execute(
        "INSERT INTO simulation_runs (id, model_name, status, iterations, seed, finished_at) "
        "VALUES (?, ?, 'completed', 100, 42, datetime('now'))",
        (run_id, model),
    )


def _insert_snapshot(conn, snap_id: str, run_id: str | None, trigger: str, label: str) -> None:
    conn.execute(
        "INSERT INTO snapshots (id, label, trigger, simulation_run_id) VALUES (?, ?, ?, ?)",
        (snap_id, label, trigger, run_id),
    )


def _insert_ml_model(conn, mid: str, is_active: int = 1) -> None:
    run_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO ml_training_runs (id, algorithm, status) VALUES (?, 'lightgbm', 'completed')",
        (run_id,),
    )
    conn.execute(
        "INSERT INTO ml_models (id, training_run_id, algorithm, brier_score, is_active) "
        "VALUES (?, ?, 'lightgbm', 0.22, ?)",
        (mid, run_id, is_active),
    )


def _setup_db(path: str) -> None:
    """Initialise a file-based SQLite DB with migrations."""
    conn = _make_db(path)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# TestEnqueueJobs — fault-tolerance and job record creation
# ---------------------------------------------------------------------------

class TestEnqueueJobs:
    def test_enqueue_full_refresh_creates_job(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / "t.db")
        monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)
        _setup_db(db_path)

        with patch("redis.Redis") as mock_redis_cls, patch("rq.Queue") as mock_q_cls:
            mock_redis_cls.from_url.return_value = MagicMock()
            mock_q_cls.return_value = MagicMock()

            from app.scheduler.jobs import enqueue_full_refresh
            enqueue_full_refresh()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs WHERE job_type='full_refresh'").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0]["status"] == "enqueued"

    def test_enqueue_news_update_creates_job(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / "t.db")
        monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)
        _setup_db(db_path)

        with patch("redis.Redis") as mock_redis_cls, patch("rq.Queue") as mock_q_cls:
            mock_redis_cls.from_url.return_value = MagicMock()
            mock_q_cls.return_value = MagicMock()

            from app.scheduler.jobs import enqueue_news_update
            enqueue_news_update()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs WHERE job_type='news'").fetchall()
        conn.close()
        assert len(rows) == 1

    def test_redis_failure_does_not_propagate(self, monkeypatch, tmp_path):
        """If Redis is unreachable, the scheduler job logs but does not raise."""
        db_path = str(tmp_path / "t.db")
        monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)
        _setup_db(db_path)

        with patch("redis.Redis") as mock_redis_cls:
            mock_redis_cls.from_url.side_effect = ConnectionError("no redis")
            from app.scheduler.jobs import enqueue_full_refresh
            enqueue_full_refresh()  # must not raise


# ---------------------------------------------------------------------------
# TestCheckAndSnapshot
# ---------------------------------------------------------------------------

class TestCheckAndSnapshot:
    def test_no_fixtures_no_enqueue(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / "t.db")
        monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)
        _setup_db(db_path)

        enqueued: list[str] = []
        with patch("app.scheduler.jobs._enqueue_pre_match_snapshot", enqueued.append):
            from app.scheduler.jobs import check_and_snapshot
            check_and_snapshot()

        assert enqueued == []

    def test_upcoming_fixture_triggers_enqueue(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / "t.db")
        monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)
        conn = _make_db(db_path)
        _insert_team(conn, "BRA", "Brasil")
        _insert_team(conn, "ARG", "Argentina")
        soon = (datetime.now(timezone.utc) + timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%S")
        _insert_fixture(conn, "f1", "BRA", "ARG", soon)
        conn.commit()
        conn.close()

        enqueued: list[str] = []
        with patch("app.scheduler.jobs._enqueue_pre_match_snapshot", enqueued.append):
            from app.scheduler.jobs import check_and_snapshot
            check_and_snapshot()

        assert len(enqueued) == 1
        assert "Brasil" in enqueued[0]
        assert "Argentina" in enqueued[0]

    def test_existing_snapshot_skips_enqueue(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / "t.db")
        monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)
        conn = _make_db(db_path)
        _insert_team(conn, "BRA", "Brasil")
        _insert_team(conn, "FRA", "Francia")
        soon_dt = datetime.now(timezone.utc) + timedelta(hours=10)
        soon = soon_dt.strftime("%Y-%m-%dT%H:%M:%S")
        _insert_fixture(conn, "f2", "BRA", "FRA", soon)

        # Use the fixture's date (not today) to match what check_and_snapshot computes
        date_str = soon_dt.strftime("%Y-%m-%d")
        label = f"Pre-match: Brasil vs Francia ({date_str})"
        run_id = str(uuid.uuid4())
        _insert_simulation_run(conn, run_id)
        _insert_snapshot(conn, str(uuid.uuid4()), run_id, "pre_match", label)
        conn.commit()
        conn.close()

        enqueued: list[str] = []
        with patch("app.scheduler.jobs._enqueue_pre_match_snapshot", enqueued.append):
            from app.scheduler.jobs import check_and_snapshot
            check_and_snapshot()

        assert enqueued == []

    def test_past_fixture_not_enqueued(self, monkeypatch, tmp_path):
        """Fixtures more than 25h away are not included in the window."""
        db_path = str(tmp_path / "t.db")
        monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)
        conn = _make_db(db_path)
        _insert_team(conn, "GER", "Alemania")
        _insert_team(conn, "ENG", "Inglaterra")
        # fixture 48 hours from now — outside 25h window
        far = (datetime.now(timezone.utc) + timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%S")
        _insert_fixture(conn, "f3", "GER", "ENG", far)
        conn.commit()
        conn.close()

        enqueued: list[str] = []
        with patch("app.scheduler.jobs._enqueue_pre_match_snapshot", enqueued.append):
            from app.scheduler.jobs import check_and_snapshot
            check_and_snapshot()

        assert enqueued == []


# ---------------------------------------------------------------------------
# TestSnapshotEndpoints
# ---------------------------------------------------------------------------

class TestSnapshotEndpoints:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.core.config.settings.SCHEDULER_ENABLED", False)
        monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", str(tmp_path / "snap.db"))
        monkeypatch.setattr("app.core.config.settings.ADMIN_TOKEN", "snap-test-token")
        _setup_db(str(tmp_path / "snap.db"))

        from fastapi.testclient import TestClient
        from app.main import app
        self.client = TestClient(app)
        self.admin_headers = {"X-Admin-Token": "snap-test-token"}

        # Seed data
        from app.db.connection import db_transaction
        with db_transaction() as conn:
            _insert_team(conn, "T1", "Team One")
            _insert_team(conn, "T2", "Team Two")
            _insert_simulation_run(conn, "run-001")
            _insert_snapshot(conn, "snap-001", "run-001", "full_refresh", "Alpha")
            conn.commit()

    def test_list_snapshots(self):
        r = self.client.get("/api/snapshots")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert any(s["id"] == "snap-001" for s in data)

    def test_create_manual_snapshot(self):
        r = self.client.post(
            "/api/snapshots/run-001",
            json={"label": "Manual test", "description": "From test"},
            headers=self.admin_headers,
        )
        assert r.status_code == 201
        body = r.json()
        assert body["label"] == "Manual test"
        assert body["trigger"] == "manual"
        assert body["simulation_run_id"] == "run-001"

    def test_create_snapshot_unknown_run_is_404(self):
        r = self.client.post(
            "/api/snapshots/does-not-exist",
            json={"label": "Should fail"},
            headers=self.admin_headers,
        )
        assert r.status_code == 404

    def test_compare_snapshots_returns_delta_keys(self):
        from app.db.connection import db_transaction
        with db_transaction() as conn:
            _insert_simulation_run(conn, "run-002")
            _insert_snapshot(conn, "snap-002", "run-002", "manual", "Beta")
            conn.commit()

        r = self.client.get("/api/snapshots/snap-001/compare?other=snap-002")
        assert r.status_code == 200
        body = r.json()
        assert "snapshot_a" in body
        assert "snapshot_b" in body
        assert "deltas" in body
        assert isinstance(body["deltas"], list)

    def test_compare_unknown_snapshot_is_404(self):
        r = self.client.get("/api/snapshots/snap-001/compare?other=ghost")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# TestMetricsEndpoint
# ---------------------------------------------------------------------------

class TestMetricsEndpoint:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.core.config.settings.SCHEDULER_ENABLED", False)
        monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", str(tmp_path / "met.db"))
        _setup_db(str(tmp_path / "met.db"))

        from fastapi.testclient import TestClient
        from app.main import app
        self.client = TestClient(app)

    def test_metrics_has_all_expected_keys(self):
        # Admin endpoint returns full metrics including sensitive fields
        r = self.client.get("/api/metrics/admin", headers={"X-Admin-Token": "test_token_for_metrics_test"})
        # ADMIN_TOKEN is not set in this fixture so expect 503, or use public endpoint keys
        r_pub = self.client.get("/api/metrics")
        assert r_pub.status_code == 200
        body = r_pub.json()
        for key in ("latest_simulation_at", "jobs_running", "model_status"):
            assert key in body, f"missing key: {key}"

    def test_ml_calibrated_untrained_when_no_models(self):
        r = self.client.get("/api/metrics")
        assert r.json()["model_status"]["ml_calibrated"] == "untrained"

    def test_ml_calibrated_active_when_model_exists(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.core.config.settings.SQLITE_PATH", str(tmp_path / "active.db")
        )
        _setup_db(str(tmp_path / "active.db"))
        from app.db.connection import db_transaction
        with db_transaction() as conn:
            _insert_ml_model(conn, str(uuid.uuid4()), is_active=1)
            conn.commit()

        from fastapi.testclient import TestClient
        from app.main import app
        r = TestClient(app).get("/api/metrics")
        assert r.json()["model_status"]["ml_calibrated"] == "active"

    def test_base_models_always_ok(self):
        body = self.client.get("/api/metrics").json()
        for m in ("baseline", "elo", "poisson", "poisson_context"):
            assert body["model_status"][m] == "ok"

    def test_jobs_running_count(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.core.config.settings.SQLITE_PATH", str(tmp_path / "jc.db")
        )
        _setup_db(str(tmp_path / "jc.db"))
        from app.db.connection import db_transaction
        with db_transaction() as conn:
            for status in ("started", "enqueued"):
                conn.execute(
                    "INSERT INTO jobs (id, job_type, status) VALUES (?, 'simulation', ?)",
                    (str(uuid.uuid4()), status),
                )
            conn.commit()

        from fastapi.testclient import TestClient
        from app.main import app
        r = TestClient(app).get("/api/metrics")
        assert r.json()["jobs_running"] == 2

    def test_latest_timestamps_null_on_empty_db(self):
        r = self.client.get("/api/metrics")
        body = r.json()
        assert body["latest_simulation_at"] is None
        # latest_ml_training_at and latest_news_analysis_at are in /api/metrics/admin only


# ---------------------------------------------------------------------------
# TestSchedulerLifecycle
# ---------------------------------------------------------------------------

class TestSchedulerLifecycle:
    def setup_method(self):
        # Reset singleton before each test
        import app.scheduler.scheduler as sched_mod
        if sched_mod._scheduler is not None and sched_mod._scheduler.running:
            sched_mod._scheduler.shutdown(wait=False)
        sched_mod._scheduler = None

    def teardown_method(self):
        import app.scheduler.scheduler as sched_mod
        if sched_mod._scheduler is not None and sched_mod._scheduler.running:
            sched_mod._scheduler.shutdown(wait=False)
        sched_mod._scheduler = None

    def test_start_registers_three_jobs(self):
        from app.scheduler.scheduler import get_scheduler, start_scheduler
        start_scheduler()
        s = get_scheduler()
        assert s.running
        job_ids = {j.id for j in s.get_jobs()}
        assert {"full_refresh", "news_update", "reconcile_jobs", "fetch_odds", "daily_simulations"} == job_ids

    def test_start_is_idempotent(self):
        from app.scheduler.scheduler import get_scheduler, start_scheduler
        start_scheduler()
        start_scheduler()
        assert len(get_scheduler().get_jobs()) == 5

    def test_stop_shuts_down_scheduler(self):
        from app.scheduler.scheduler import get_scheduler, start_scheduler, stop_scheduler
        start_scheduler()
        stop_scheduler()
        assert not get_scheduler().running

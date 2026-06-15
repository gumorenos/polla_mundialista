"""Tests for DELETE /api/jobs/{job_id} — cancel job endpoint."""

from __future__ import annotations

import sqlite3
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.migrations import run_migrations
from app.db.repositories.jobs import JobRepository


def _bootstrap_db(path: str) -> None:
    """Create and migrate a SQLite file DB at *path*."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.commit()
    conn.close()


def _insert_job(path: str, status: str) -> str:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    job_id = str(uuid.uuid4())
    JobRepository(conn).create(
        {"id": job_id, "rq_job_id": f"rq-{job_id[:8]}", "job_type": "test_job", "status": status}
    )
    conn.commit()
    conn.close()
    return job_id


@pytest.fixture()
def setup(monkeypatch, tmp_path):
    db_path = str(tmp_path / "cancel.db")
    monkeypatch.setattr("app.core.config.settings.SCHEDULER_ENABLED", False)
    monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)
    monkeypatch.setattr("app.core.config.settings.ADMIN_TOKEN", "testtoken")
    _bootstrap_db(db_path)
    return db_path


@pytest.fixture()
def _mock_rq():
    """Patch RQ/redis so tests don't need a real Redis."""
    with patch("app.api.routes.jobs.redis_lib") as mock_redis, \
         patch("app.api.routes.jobs.RQJob") as mock_rq_job_cls:
        mock_redis.from_url.return_value = MagicMock()
        mock_rq_job_cls.fetch.return_value = MagicMock()
        yield


def test_cancel_enqueued_job_returns_200(setup, _mock_rq):
    """DELETE /api/jobs/{id} with valid token cancels an enqueued job."""
    from app.main import app

    job_id = _insert_job(setup, "enqueued")
    client = TestClient(app)
    resp = client.delete(f"/api/jobs/{job_id}", headers={"X-Admin-Token": "testtoken"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["cancelled"] is True
    assert data["job_id"] == job_id


def test_cancel_started_job_returns_200(setup, _mock_rq):
    """DELETE /api/jobs/{id} also cancels a running job."""
    from app.main import app

    job_id = _insert_job(setup, "started")
    client = TestClient(app)
    resp = client.delete(f"/api/jobs/{job_id}", headers={"X-Admin-Token": "testtoken"})
    assert resp.status_code == 200
    assert resp.json()["cancelled"] is True


def test_cancel_completed_job_returns_409(setup, _mock_rq):
    """Cannot cancel an already completed job."""
    from app.main import app

    job_id = _insert_job(setup, "completed")
    client = TestClient(app)
    resp = client.delete(f"/api/jobs/{job_id}", headers={"X-Admin-Token": "testtoken"})
    assert resp.status_code == 409


def test_cancel_nonexistent_job_returns_404(setup, _mock_rq):
    """Cancelling a job that does not exist returns 404."""
    from app.main import app

    client = TestClient(app)
    resp = client.delete(f"/api/jobs/{uuid.uuid4()}", headers={"X-Admin-Token": "testtoken"})
    assert resp.status_code == 404


def test_cancel_without_token_returns_403(setup):
    """DELETE /api/jobs/{id} requires admin token."""
    from app.main import app

    job_id = _insert_job(setup, "enqueued")
    client = TestClient(app)
    resp = client.delete(f"/api/jobs/{job_id}")
    assert resp.status_code == 403


def test_cancelled_job_status_persisted(setup, _mock_rq):
    """After cancellation the DB record shows status='cancelled'."""
    from app.main import app
    from app.db.connection import db_transaction

    job_id = _insert_job(setup, "enqueued")
    client = TestClient(app)
    client.delete(f"/api/jobs/{job_id}", headers={"X-Admin-Token": "testtoken"})

    with db_transaction() as conn:
        job = JobRepository(conn).get_by_id(job_id)

    assert job is not None
    assert job["status"] == "cancelled"
    assert job["finished_at"] is not None

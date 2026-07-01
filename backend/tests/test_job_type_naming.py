"""Tests for Fase 1 — job_type naming convention.

POST /api/simulations/run          -> simulation_full_<model>
POST /api/simulations/bracket/run  -> simulation_bracket_<model>
POST /api/pipelines/run-all-models -> simulation_full_<model> for each model
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.migrations import run_migrations


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


@pytest.fixture()
def client(monkeypatch, tmp_path):
    db_path = str(tmp_path / "jobtype.db")
    monkeypatch.setattr("app.core.config.settings.SCHEDULER_ENABLED", False)
    monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)
    monkeypatch.setattr("app.core.config.settings.ADMIN_TOKEN", "testtoken")
    _bootstrap_db(db_path)

    from app.main import app
    yield TestClient(app), db_path


@pytest.fixture()
def _mock_rq():
    # simulations.py / pipelines.py / job_helper.py do module-level
    # `from redis import Redis` / `from rq import Queue` — patch the names
    # as bound in each of those modules, not the source `redis`/`rq` modules.
    targets = [
        "app.api.routes.simulations.Redis", "app.api.routes.simulations.Queue",
        "app.api.routes.pipelines.Redis", "app.api.routes.pipelines.Queue",
        "app.core.job_helper.Redis", "app.core.job_helper.Queue",
    ]
    patchers = [patch(t) for t in targets]
    mocks = [p.start() for p in patchers]
    mock_queue = MagicMock()
    mock_queue.enqueue.return_value = MagicMock(id="rq-fake")
    for m in mocks:
        m.from_url.return_value = MagicMock()
        m.return_value = mock_queue
    try:
        yield mock_queue
    finally:
        for p in patchers:
            p.stop()


class TestFullSimulationJobType:
    def test_run_endpoint_creates_simulation_full_job(self, client, _mock_rq):
        c, db_path = client
        resp = c.post(
            "/api/simulations/run",
            json={"model_name": "poisson"},
            headers={"X-Admin-Token": "testtoken"},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]
        row = _query(db_path, "SELECT job_type FROM jobs WHERE id = ?", (job_id,))[0]
        assert row["job_type"] == "simulation_full_poisson"


class TestBracketSimulationJobType:
    def test_bracket_run_endpoint_creates_simulation_bracket_job(self, client, _mock_rq):
        c, db_path = client
        resp = c.post(
            "/api/simulations/bracket/run?model=elo",
            headers={"X-Admin-Token": "testtoken"},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]
        row = _query(db_path, "SELECT job_type FROM jobs WHERE id = ?", (job_id,))[0]
        assert row["job_type"] == "simulation_bracket_elo"


class TestRunAllModelsJobType:
    def test_run_all_models_uses_full_naming(self, client, _mock_rq):
        c, db_path = client
        resp = c.post(
            "/api/pipelines/run-all-models",
            headers={"X-Admin-Token": "testtoken"},
        )
        assert resp.status_code == 200
        job_types = {j["job_id"] for j in resp.json()["jobs"]}
        rows = _query(db_path, "SELECT job_type FROM jobs WHERE id IN (%s)" % ",".join("?" * len(job_types)), tuple(job_types))
        types = {r["job_type"] for r in rows}
        assert all(t.startswith("simulation_full_") for t in types)
        assert "simulation_full_baseline" in types
        assert "simulation_full_ml_calibrated" in types

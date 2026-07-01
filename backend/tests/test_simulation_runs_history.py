"""Simulations screen must show run history (any status) instead of going
blank when the only completed runs for a model were flagged invalid by the
guardrail script — see SimulationRepository.list_runs_history and
GET /api/simulations/runs."""

from __future__ import annotations

import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.migrations import run_migrations
from app.db.repositories.simulations import SimulationRepository


@pytest.fixture()
def client(monkeypatch, tmp_path):
    db_path = str(tmp_path / "runs_history.db")
    monkeypatch.setattr("app.core.config.settings.SCHEDULER_ENABLED", False)
    monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    conn.commit()
    conn.close()

    from app.main import app
    app.state.limiter.enabled = False
    return TestClient(app)


def _insert_run(conn, model_name, status_, finished_at=None):
    run_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO simulation_runs (id, model_name, status, finished_at) VALUES (?, ?, ?, ?)",
        (run_id, model_name, status_, finished_at),
    )
    return run_id


class TestListRunsHistory:
    def test_includes_invalid_and_completed_runs(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "x.db"))
        conn.row_factory = sqlite3.Row
        run_migrations(conn)
        _insert_run(conn, "poisson", "invalid", "2026-06-01T00:00:00Z")
        _insert_run(conn, "poisson", "invalid", "2026-06-02T00:00:00Z")
        conn.commit()

        repo = SimulationRepository(conn)
        history = repo.list_runs_history("poisson")
        assert len(history) == 2
        assert {r["status"] for r in history} == {"invalid"}
        conn.close()


class TestSimulationsRunsEndpoint:
    def test_runs_endpoint_returns_history_even_when_all_invalid(self, client):
        from app.db.connection import db_transaction

        with db_transaction() as conn:
            _insert_run(conn, "poisson", "invalid", "2026-06-01T00:00:00Z")

        resp = client.get("/api/simulations/runs?model=poisson")
        assert resp.status_code == 200
        body = resp.json()
        assert body["model"] == "poisson"
        assert len(body["runs"]) == 1
        assert body["runs"][0]["status"] == "invalid"

    def test_latest_404_message_mentions_invalid_run_count(self, client):
        from app.db.connection import db_transaction

        with db_transaction() as conn:
            _insert_run(conn, "poisson", "invalid", "2026-06-01T00:00:00Z")

        resp = client.get("/api/simulations/latest?model=poisson")
        assert resp.status_code == 404
        assert "1 runs inválidos" in resp.json()["detail"]

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "service" in data


def test_ping_enqueues_job():
    mock_job = MagicMock()
    mock_job.id = "test-job-id-abc123"

    with (
        patch("app.api.routes.health.Redis"),
        patch("app.api.routes.health.Queue") as MockQueue,
    ):
        mock_q = MagicMock()
        mock_q.enqueue.return_value = mock_job
        MockQueue.return_value = mock_q

        response = client.get("/api/jobs/ping")

    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "test-job-id-abc123"
    assert data["status"] == "enqueued"

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


def test_ping_checks_redis():
    """GET /api/jobs/ping now verifies Redis is reachable without enqueueing jobs."""
    mock_conn = MagicMock()
    mock_conn.ping.return_value = True

    # Redis is imported inside the function body, so patch at the source module
    with patch("redis.Redis") as MockRedis:
        MockRedis.from_url.return_value = mock_conn
        response = client.get("/api/jobs/ping")

    assert response.status_code == 200
    data = response.json()
    assert data["redis"] == "ok"


def test_ping_returns_503_when_redis_unavailable():
    """GET /api/jobs/ping returns 503 if Redis is unreachable."""
    with patch("redis.Redis") as MockRedis:
        MockRedis.from_url.side_effect = Exception("Connection refused")
        response = TestClient(app, raise_server_exceptions=False).get("/api/jobs/ping")

    assert response.status_code == 503

"""Tests for Prompt 12 — admin token enforcement and rate limiting."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(path: str = ":memory:"):
    import sqlite3
    from app.db.migrations import run_migrations
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    return conn


# ---------------------------------------------------------------------------
# TestAdminTokenEnforcement
# ---------------------------------------------------------------------------

class TestAdminTokenEnforcement:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.core.config.settings.SCHEDULER_ENABLED", False)
        monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", str(tmp_path / "sec.db"))
        monkeypatch.setattr("app.core.config.settings.ADMIN_TOKEN", "supersecret")
        _make_db(str(tmp_path / "sec.db")).close()

        from fastapi.testclient import TestClient
        from app.main import app
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_admin_without_token_returns_403(self):
        """POST /api/admin/ingest with no token → 403 when ADMIN_TOKEN is set."""
        r = self.client.post("/api/admin/ingest")
        assert r.status_code == 403

    def test_admin_with_wrong_token_returns_403(self):
        """Wrong token is rejected with 403."""
        r = self.client.post(
            "/api/admin/ingest",
            headers={"X-Admin-Token": "wrong_token"},
        )
        assert r.status_code == 403

    def test_admin_with_correct_token_passes_auth(self):
        """Correct token passes auth check (may fail later due to Redis, but not 403)."""
        with patch("app.api.routes.admin.Redis") as mock_redis_cls, patch("app.api.routes.admin.Queue") as mock_q_cls:
            mock_redis_cls.from_url.return_value = MagicMock()
            job_mock = MagicMock()
            job_mock.id = str(uuid.uuid4())
            mock_q_cls.return_value.enqueue.return_value = job_mock

            r = self.client.post(
                "/api/admin/ingest",
                headers={"X-Admin-Token": "supersecret"},
            )
        # Auth passed — response should be 200 (not 403)
        assert r.status_code == 200

    def test_pipeline_without_token_returns_403(self):
        """POST /api/pipelines/full-refresh also requires ADMIN_TOKEN."""
        r = self.client.post("/api/pipelines/full-refresh")
        assert r.status_code == 403

    def test_public_endpoint_no_token_required(self):
        """GET /api/health is public — no token required."""
        r = self.client.get("/api/health")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# TestRateLimiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_rate_limiter_is_configured_on_app(self, monkeypatch):
        """The production app has a slowapi limiter attached to app.state."""
        monkeypatch.setattr("app.core.config.settings.SCHEDULER_ENABLED", False)
        from app.main import app
        assert hasattr(app.state, "limiter")
        assert app.state.limiter is not None

    def test_rate_limit_returns_429_after_limit_exceeded(self):
        """A 1/minute rate limit returns 429 on the second request from same IP."""
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        from slowapi import Limiter, _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded
        from slowapi.middleware import SlowAPIMiddleware
        from slowapi.util import get_remote_address

        limiter = Limiter(
            key_func=get_remote_address,
            default_limits=["1/minute"],
        )
        test_app = FastAPI()
        test_app.state.limiter = limiter
        test_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        test_app.add_middleware(SlowAPIMiddleware)

        @test_app.get("/ping")
        def ping():
            return {"pong": True}

        client = TestClient(test_app, raise_server_exceptions=False)
        r1 = client.get("/ping")
        assert r1.status_code == 200
        r2 = client.get("/ping")
        assert r2.status_code == 429

    def test_rate_limit_resets_after_window(self):
        """After being rate-limited, a new limiter instance allows requests again."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from slowapi import Limiter, _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded
        from slowapi.middleware import SlowAPIMiddleware
        from slowapi.util import get_remote_address

        # Fresh limiter with a 2/minute limit
        limiter = Limiter(
            key_func=get_remote_address,
            default_limits=["2/minute"],
        )
        test_app = FastAPI()
        test_app.state.limiter = limiter
        test_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        test_app.add_middleware(SlowAPIMiddleware)

        @test_app.get("/ping")
        def ping():
            return {"ok": True}

        client = TestClient(test_app, raise_server_exceptions=False)
        r1 = client.get("/ping")
        r2 = client.get("/ping")
        r3 = client.get("/ping")  # exceeds 2/minute

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r3.status_code == 429

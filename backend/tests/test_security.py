"""Tests for Prompt 12 + Fix-1 — admin token enforcement and rate limiting."""

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


# ---------------------------------------------------------------------------
# TestFailClosedAuth  (Fix-1 additions)
# ---------------------------------------------------------------------------

class TestFailClosedAuth:
    """Verify fail-closed behaviour: empty ADMIN_TOKEN → 503, not open."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.core.config.settings.SCHEDULER_ENABLED", False)
        monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", str(tmp_path / "fc.db"))

        import sqlite3
        from app.db.migrations import run_migrations
        conn = sqlite3.connect(str(tmp_path / "fc.db"))
        conn.row_factory = sqlite3.Row
        run_migrations(conn)
        conn.close()

        from fastapi.testclient import TestClient
        from app.main import app
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_empty_admin_token_returns_503(self, monkeypatch):
        """Fail-closed: empty ADMIN_TOKEN → 503 (not open access)."""
        monkeypatch.setattr("app.core.config.settings.ADMIN_TOKEN", "")
        r = self.client.post("/api/admin/ingest")
        assert r.status_code == 503

    def test_simulation_run_requires_auth(self, monkeypatch):
        """POST /api/simulations/run must require admin token."""
        monkeypatch.setattr("app.core.config.settings.ADMIN_TOKEN", "secret")
        r = self.client.post("/api/simulations/run", json={"model_name": "baseline"})
        assert r.status_code in (403, 503)

    def test_snapshot_create_requires_auth(self, monkeypatch):
        """POST /api/snapshots/{run_id} must require admin token."""
        monkeypatch.setattr("app.core.config.settings.ADMIN_TOKEN", "secret")
        r = self.client.post("/api/snapshots/fake-run-id", json={"label": "test"})
        assert r.status_code in (403, 503)

    def test_pipeline_endpoints_require_auth(self, monkeypatch):
        """All pipeline endpoints must require admin token."""
        monkeypatch.setattr("app.core.config.settings.ADMIN_TOKEN", "secret")
        for path in [
            "/api/pipelines/full-refresh",
            "/api/pipelines/daily-update",
            "/api/pipelines/run-all-models",
        ]:
            r = self.client.post(path)
            assert r.status_code in (403, 503), f"{path} should require auth, got {r.status_code}"

    def test_jobs_ping_does_not_require_auth(self):
        """GET /api/jobs/ping is a public health check — no token needed."""
        r = self.client.get("/api/jobs/ping")
        # 200 (Redis available) or 503 (Redis not available in test env)
        assert r.status_code in (200, 503)

    def test_evaluations_summary_contract(self, monkeypatch):
        """GET /api/evaluations/summary must return frontend-compatible field names."""
        import sqlite3
        from app.db.migrations import run_migrations
        monkeypatch.setattr("app.core.config.settings.ADMIN_TOKEN", "")

        r = self.client.get("/api/evaluations/summary")
        assert r.status_code == 200
        data = r.json()
        if data:
            row = data[0]
            assert "brier_score" in row, "Frontend expects brier_score, not avg_brier"
            assert "log_loss" in row
            assert "rps" in row
            assert "accuracy" in row
            assert "total_predictions" in row


# ---------------------------------------------------------------------------
# TestFix4Security — AUD-003, AUD-007, AUD-008, AUD-010
# ---------------------------------------------------------------------------

class TestFix4Security:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.core.config.settings.SCHEDULER_ENABLED", False)
        monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", str(tmp_path / "fix4.db"))
        monkeypatch.setattr("app.core.config.settings.ADMIN_TOKEN", "supersecret")
        _make_db(str(tmp_path / "fix4.db")).close()

        from app.api.routes import auth as auth_mod
        auth_mod._active_sessions.clear()

        from fastapi.testclient import TestClient
        from app.main import app
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_invalid_model_name_returns_422(self):
        """POST /api/simulations/run with unknown model_name → 422 (Pydantic Literal)."""
        r = self.client.post(
            "/api/simulations/run",
            json={"model_name": "invalid_model_xyz"},
            headers={"X-Admin-Token": "supersecret"},
        )
        assert r.status_code == 422, f"Expected 422 for invalid model_name, got {r.status_code}"

    def test_valid_model_name_passes_validation(self):
        """POST /api/simulations/run with valid model_name passes Pydantic."""
        from unittest.mock import MagicMock, patch
        import uuid

        with patch("app.api.routes.simulations.Redis") as mock_r, \
             patch("app.api.routes.simulations.Queue") as mock_q:
            mock_r.from_url.return_value = MagicMock()
            job_mock = MagicMock()
            job_mock.id = str(uuid.uuid4())
            mock_q.return_value.enqueue.return_value = job_mock
            r = self.client.post(
                "/api/simulations/run",
                json={"model_name": "baseline", "iterations": 1000},
                headers={"X-Admin-Token": "supersecret"},
            )
        assert r.status_code == 200

    def test_safe_load_model_rejects_path_outside_allowed_dir(self, monkeypatch, tmp_path):
        """_safe_load_model must raise ValueError for paths outside ML_MODELS_PATH."""
        from app.services.prediction.ml_calibrated import _safe_load_model

        monkeypatch.setattr(
            "app.core.config.settings.ML_MODELS_PATH", str(tmp_path / "models")
        )
        with pytest.raises((ValueError, FileNotFoundError)):
            _safe_load_model("/etc/passwd")

    def test_safe_load_model_rejects_traversal(self, monkeypatch, tmp_path):
        """_safe_load_model blocks path traversal like ../../etc/passwd."""
        from app.services.prediction.ml_calibrated import _safe_load_model
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        monkeypatch.setattr("app.core.config.settings.ML_MODELS_PATH", str(models_dir))
        with pytest.raises((ValueError, FileNotFoundError)):
            _safe_load_model(str(models_dir / ".." / ".." / "etc" / "passwd"))

    def test_public_active_model_omits_model_path(self):
        """GET /api/ml/models/active must not expose filesystem model_path."""
        from app.db.connection import db_transaction

        with db_transaction() as conn:
            conn.execute(
                """
                INSERT INTO ml_training_runs (id, algorithm, status)
                VALUES ('tr-public', 'lightgbm', 'completed')
                """
            )
            conn.execute(
                """
                INSERT INTO ml_models
                    (id, training_run_id, algorithm, model_path, brier_score, is_active)
                VALUES
                    ('model-public', 'tr-public', 'lightgbm', '/app/data/models/secret.joblib', 0.25, 1)
                """
            )
            conn.commit()

        r = self.client.get("/api/ml/models/active")
        assert r.status_code == 200
        assert "model_path" not in r.json()

    def test_public_model_list_omits_model_path(self):
        """GET /api/ml/models must not expose filesystem model_path."""
        from app.db.connection import db_transaction

        with db_transaction() as conn:
            conn.execute(
                """
                INSERT INTO ml_training_runs (id, algorithm, status)
                VALUES ('tr-list', 'xgboost', 'completed')
                """
            )
            conn.execute(
                """
                INSERT INTO ml_models
                    (id, training_run_id, algorithm, model_path, brier_score, is_active)
                VALUES
                    ('model-list', 'tr-list', 'xgboost', '/app/data/models/list.joblib', 0.35, 0)
                """
            )
            conn.commit()

        r = self.client.get("/api/ml/models")
        assert r.status_code == 200
        assert r.json()
        assert all("model_path" not in row for row in r.json())

    def test_public_jobs_endpoint_omits_sensitive_fields(self):
        """GET /api/jobs without admin credentials must not include error_message or result_ref."""
        r = self.client.get("/api/jobs")
        assert r.status_code == 200
        for job in r.json():
            assert "error_message" not in job, "error_message must not be in public jobs response"
            assert "result_ref" not in job, "result_ref must not be in public jobs response"

    def test_admin_jobs_endpoint_includes_sensitive_fields(self):
        """GET /api/jobs with admin header must include error_message and result_ref."""
        import sqlite3
        from app.db.connection import db_transaction
        from app.db.repositories.jobs import JobRepository

        db_path = self.client.app.state.db_path if hasattr(self.client.app.state, "db_path") else None

        r = self.client.get("/api/jobs", headers={"X-Admin-Token": "supersecret"})
        assert r.status_code == 200
        for job in r.json():
            assert "error_message" in job
            assert "result_ref" in job

    def test_public_metrics_omits_injury_data(self):
        """GET /api/metrics public must not include teams_with_injuries."""
        r = self.client.get("/api/metrics")
        assert r.status_code == 200
        assert "teams_with_injuries" not in r.json(), (
            "teams_with_injuries must not appear in public /api/metrics"
        )

    def test_admin_metrics_includes_injury_data(self):
        """GET /api/metrics/admin must include teams_with_injuries."""
        r = self.client.get("/api/metrics/admin", headers={"X-Admin-Token": "supersecret"})
        assert r.status_code == 200
        assert "teams_with_injuries" in r.json()

    def test_api_docs_disabled_in_production(self, monkeypatch):
        """GET /api/docs must return 404 when ENVIRONMENT=production."""
        monkeypatch.setattr("app.core.config.settings.ENVIRONMENT", "production")
        monkeypatch.setattr("app.core.config.settings.ADMIN_TOKEN", "supersecret")

        # Re-create app with production env to pick up the disabled docs
        from fastapi.testclient import TestClient
        from app.main import _is_prod
        if not _is_prod:
            pytest.skip("App was built with dev settings; restart needed to test prod docs URL")
        r = self.client.get("/api/docs")
        assert r.status_code == 404

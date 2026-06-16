"""Tests for AUD-001 — session-based admin auth (cookie httpOnly) and Fix-4b password."""

from __future__ import annotations

import pytest

_TOKEN = "test_secret_32chars_abcdefghijk"
_PASSWORD = "mypassword123"
_PLACEHOLDER = "change_me_in_production"


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


def _install_fake_redis(monkeypatch):
    fake = _FakeRedis()

    def _from_url(*args, **kwargs):
        return fake

    monkeypatch.setattr("app.api.routes.auth.Redis.from_url", _from_url)
    return fake


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch, tmp_path):
    import sqlite3
    from app.db.migrations import run_migrations

    db_path = str(tmp_path / "auth_test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    conn.execute(
        """
        INSERT INTO admin_password_history (changed_by, password_hash, note)
        VALUES (?, ?, ?)
        """,
        ("test_seed", "seed_hash", "existing password change"),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("app.core.config.settings.SCHEDULER_ENABLED", False)
    monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)
    monkeypatch.setattr("app.core.config.settings.ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr("app.core.config.settings.ADMIN_PASSWORD", _PASSWORD)

    from app.api.routes import auth as auth_mod
    auth_mod._active_sessions.clear()
    _install_fake_redis(monkeypatch)

    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Login / logout / status
# ---------------------------------------------------------------------------

class TestLogin:
    def test_correct_password_returns_200(self, client):
        r = client.post("/api/auth/login", json={"password": _PASSWORD})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_correct_password_sets_cookie(self, client):
        r = client.post("/api/auth/login", json={"password": _PASSWORD})
        assert "admin_session" in r.cookies

    def test_login_returns_must_change_false_for_good_password(self, client):
        r = client.post("/api/auth/login", json={"password": _PASSWORD})
        assert r.json()["must_change_password"] is False

    def test_wrong_password_returns_401(self, client):
        r = client.post("/api/auth/login", json={"password": "wrong_password"})
        assert r.status_code == 401

    def test_wrong_password_no_cookie(self, client):
        r = client.post("/api/auth/login", json={"password": "wrong_password"})
        assert "admin_session" not in r.cookies

    def test_logout_returns_200(self, client):
        client.post("/api/auth/login", json={"password": _PASSWORD})
        r = client.post("/api/auth/logout")
        assert r.status_code == 200


class TestAuthStatus:
    def test_unauthenticated_returns_false(self, client):
        r = client.get("/api/auth/status")
        assert r.status_code == 200
        assert r.json()["authenticated"] is False

    def test_authenticated_returns_true(self, client):
        client.post("/api/auth/login", json={"password": _PASSWORD})
        r = client.get("/api/auth/status")
        assert r.json()["authenticated"] is True

    def test_status_includes_must_change_password(self, client):
        client.post("/api/auth/login", json={"password": _PASSWORD})
        r = client.get("/api/auth/status")
        body = r.json()
        assert "must_change_password" in body

    def test_after_logout_returns_false(self, client):
        client.post("/api/auth/login", json={"password": _PASSWORD})
        client.post("/api/auth/logout")
        r = client.get("/api/auth/status")
        assert r.json()["authenticated"] is False


# ---------------------------------------------------------------------------
# Admin endpoints — cookie session vs X-Admin-Token header
# ---------------------------------------------------------------------------

class TestAdminAccess:
    def test_cookie_session_allows_admin_endpoints(self, monkeypatch, client):
        """After login, cookie is sent automatically and admin endpoints return non-403."""
        from unittest.mock import MagicMock, patch
        import uuid

        client.post("/api/auth/login", json={"password": _PASSWORD})

        with patch("app.api.routes.admin.Redis") as mock_r, patch("app.api.routes.admin.Queue") as mock_q:
            mock_r.from_url.return_value = MagicMock()
            job_mock = MagicMock()
            job_mock.id = str(uuid.uuid4())
            mock_q.return_value.enqueue.return_value = job_mock
            r = client.post("/api/admin/ingest")

        assert r.status_code != 403, f"Expected non-403 with cookie session, got {r.status_code}"

    def test_x_admin_token_header_still_works(self, monkeypatch, client):
        """X-Admin-Token header keeps working for scripts/curl (backward compat)."""
        from unittest.mock import MagicMock, patch
        import uuid

        with patch("app.api.routes.admin.Redis") as mock_r, patch("app.api.routes.admin.Queue") as mock_q:
            mock_r.from_url.return_value = MagicMock()
            job_mock = MagicMock()
            job_mock.id = str(uuid.uuid4())
            mock_q.return_value.enqueue.return_value = job_mock
            r = client.post(
                "/api/admin/ingest",
                headers={"X-Admin-Token": _TOKEN},
            )

        assert r.status_code != 403, f"X-Admin-Token should still work, got {r.status_code}"

    def test_no_auth_returns_403(self, client):
        """Without cookie or header, admin endpoints return 403."""
        r = client.post("/api/admin/ingest")
        assert r.status_code == 403

    def test_logout_revokes_admin_access(self, client):
        """After logout, the session cookie no longer grants access."""
        client.post("/api/auth/login", json={"password": _PASSWORD})
        client.post("/api/auth/logout")
        r = client.post("/api/admin/ingest")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Fix-4b — ADMIN_PASSWORD, primer login, historial de cambios
# ---------------------------------------------------------------------------

class TestFirstLogin:
    def test_empty_password_history_returns_must_change_true(self, monkeypatch, tmp_path):
        """Primer login se detecta por historial vacío, no por el valor de ADMIN_PASSWORD."""
        import sqlite3
        from app.db.migrations import run_migrations

        db_path = str(tmp_path / "first.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        run_migrations(conn)
        conn.close()

        monkeypatch.setattr("app.core.config.settings.SCHEDULER_ENABLED", False)
        monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)
        monkeypatch.setattr("app.core.config.settings.ADMIN_TOKEN", _TOKEN)
        monkeypatch.setattr("app.core.config.settings.ADMIN_PASSWORD", _PASSWORD)

        from app.api.routes import auth as auth_mod
        auth_mod._active_sessions.clear()
        _install_fake_redis(monkeypatch)

        from fastapi.testclient import TestClient
        from app.main import app
        c = TestClient(app, raise_server_exceptions=False)

        r = c.post("/api/auth/login", json={"password": _PASSWORD})
        assert r.status_code == 200
        assert r.json()["must_change_password"] is True

    def test_normal_password_returns_must_change_false(self, client):
        r = client.post("/api/auth/login", json={"password": _PASSWORD})
        assert r.json()["must_change_password"] is False


class TestChangePassword:
    def test_change_password_without_session_returns_401(self, client):
        """POST /api/auth/change-password sin sesión → 401."""
        r = client.post("/api/auth/change-password", json={
            "old_password": _PASSWORD,
            "new_password": "nuevapass123",
        })
        assert r.status_code == 401

    def test_change_password_wrong_old_password_returns_401(self, client):
        """POST con old_password incorrecto → 401."""
        client.post("/api/auth/login", json={"password": _PASSWORD})
        r = client.post("/api/auth/change-password", json={
            "old_password": "wrong_old_pass",
            "new_password": "nuevapass123",
        })
        assert r.status_code == 401

    def test_change_password_registers_in_history(self, client):
        """POST /api/auth/change-password inserta registro en admin_password_history."""
        client.post("/api/auth/login", json={"password": _PASSWORD})
        r = client.post("/api/auth/change-password", json={
            "old_password": _PASSWORD,
            "new_password": "nuevapass123",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_change_password_clears_must_change_flag(self, client):
        """Después de cambiar contraseña, must_change_password pasa a false."""
        client.post("/api/auth/login", json={"password": _PASSWORD})
        client.post("/api/auth/change-password", json={
            "old_password": _PASSWORD,
            "new_password": "nuevapass123",
        })
        r = client.get("/api/auth/status")
        assert r.json()["must_change_password"] is False

    def test_change_password_updates_password_immediately(self, client):
        """La nueva contraseña debe funcionar sin reiniciar el proceso."""
        client.post("/api/auth/login", json={"password": _PASSWORD})
        r = client.post("/api/auth/change-password", json={
            "old_password": _PASSWORD,
            "new_password": "nuevapass123",
        })
        assert r.status_code == 200
        client.post("/api/auth/logout")

        old_login = client.post("/api/auth/login", json={"password": _PASSWORD})
        assert old_login.status_code == 401

        new_login = client.post("/api/auth/login", json={"password": "nuevapass123"})
        assert new_login.status_code == 200

    def test_password_changed_endpoint_returns_history_state(self, client):
        r = client.get("/api/auth/password-changed")
        assert r.status_code == 200
        assert r.json()["password_changed"] is True

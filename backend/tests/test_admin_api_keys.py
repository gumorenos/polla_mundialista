"""Tests for admin API key management — POST/GET/revoke under /api/admin/api-keys."""

from __future__ import annotations

import hashlib
import sqlite3

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


@pytest.fixture()
def client(monkeypatch, tmp_path):
    db_path = str(tmp_path / "apikeys.db")
    monkeypatch.setattr("app.core.config.settings.SCHEDULER_ENABLED", False)
    monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)
    monkeypatch.setattr("app.core.config.settings.ADMIN_TOKEN", "testtoken")
    _bootstrap_db(db_path)

    from app.main import app
    app.state.limiter.enabled = False  # avoid cross-test rate-limit bleed on shared admin endpoints
    return TestClient(app)


class TestCreateApiKey:
    def test_requires_admin(self, client):
        resp = client.post("/api/admin/api-keys", json={"label": "x"})
        assert resp.status_code == 403

    def test_creates_key_and_returns_raw_once(self, client):
        resp = client.post(
            "/api/admin/api-keys", json={"label": "mi-otro-proyecto"},
            headers={"X-Admin-Token": "testtoken"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"].startswith("om26_")
        assert data["prefix"] == data["key"][:12]
        assert data["label"] == "mi-otro-proyecto"

    def test_stores_only_hash_not_raw_key(self, client, tmp_path):
        resp = client.post(
            "/api/admin/api-keys", json={"label": "x"},
            headers={"X-Admin-Token": "testtoken"},
        )
        raw_key = resp.json()["key"]
        expected_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        from app.core.config import settings
        conn = sqlite3.connect(settings.SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT key_hash FROM api_keys WHERE label = 'x'").fetchone()
        conn.close()
        assert row["key_hash"] == expected_hash
        assert raw_key not in str(dict(row))


class TestListApiKeys:
    def test_does_not_expose_raw_key_or_hash(self, client):
        client.post(
            "/api/admin/api-keys", json={"label": "proyecto-a"},
            headers={"X-Admin-Token": "testtoken"},
        )
        resp = client.get("/api/admin/api-keys", headers={"X-Admin-Token": "testtoken"})
        assert resp.status_code == 200
        keys = resp.json()["keys"]
        assert len(keys) == 1
        assert "key_hash" not in keys[0]
        assert "key" not in keys[0]
        assert keys[0]["prefix"].startswith("om26_")
        assert keys[0]["label"] == "proyecto-a"
        assert keys[0]["revoked"] == 0

    def test_requires_admin(self, client):
        resp = client.get("/api/admin/api-keys")
        assert resp.status_code == 403


class TestRevokeApiKey:
    def test_revoke_changes_state(self, client):
        created = client.post(
            "/api/admin/api-keys", json={"label": "to-revoke"},
            headers={"X-Admin-Token": "testtoken"},
        ).json()

        resp = client.post(
            f"/api/admin/api-keys/{created['id']}/revoke",
            headers={"X-Admin-Token": "testtoken"},
        )
        assert resp.status_code == 200
        assert resp.json()["revoked"] is True

        listed = client.get("/api/admin/api-keys", headers={"X-Admin-Token": "testtoken"}).json()
        key = next(k for k in listed["keys"] if k["id"] == created["id"])
        assert key["revoked"] == 1

    def test_revoked_key_no_longer_authenticates(self, client):
        created = client.post(
            "/api/admin/api-keys", json={"label": "will-be-revoked"},
            headers={"X-Admin-Token": "testtoken"},
        ).json()
        raw_key = created["key"]

        resp = client.get("/api/public/v1/teams", headers={"X-API-Key": raw_key})
        assert resp.status_code == 200

        client.post(
            f"/api/admin/api-keys/{created['id']}/revoke",
            headers={"X-Admin-Token": "testtoken"},
        )

        resp = client.get("/api/public/v1/teams", headers={"X-API-Key": raw_key})
        assert resp.status_code == 403

    def test_unknown_key_returns_404(self, client):
        resp = client.post(
            "/api/admin/api-keys/does-not-exist/revoke",
            headers={"X-Admin-Token": "testtoken"},
        )
        assert resp.status_code == 404

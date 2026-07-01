"""Tests for the public read-only API v1 (/api/public/v1/*)."""

from __future__ import annotations

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
    db_path = str(tmp_path / "public_api.db")
    monkeypatch.setattr("app.core.config.settings.SCHEDULER_ENABLED", False)
    monkeypatch.setattr("app.core.config.settings.SQLITE_PATH", db_path)
    monkeypatch.setattr("app.core.config.settings.ADMIN_TOKEN", "testtoken")
    _bootstrap_db(db_path)

    from app.main import app
    app.state.limiter.enabled = False  # avoid cross-test rate-limit bleed on shared admin endpoints
    return TestClient(app)


@pytest.fixture()
def api_key(client) -> str:
    resp = client.post(
        "/api/admin/api-keys", json={"label": "test-consumer"},
        headers={"X-Admin-Token": "testtoken"},
    )
    return resp.json()["key"]


class TestAuth:
    def test_missing_key_is_401(self, client):
        resp = client.get("/api/public/v1/teams")
        assert resp.status_code == 401

    def test_invalid_key_is_401(self, client):
        resp = client.get("/api/public/v1/teams", headers={"X-API-Key": "bogus"})
        assert resp.status_code == 401

    def test_revoked_key_is_403(self, client, tmp_path):
        created = client.post(
            "/api/admin/api-keys", json={"label": "revoke-me"},
            headers={"X-Admin-Token": "testtoken"},
        ).json()
        client.post(f"/api/admin/api-keys/{created['id']}/revoke", headers={"X-Admin-Token": "testtoken"})
        resp = client.get("/api/public/v1/teams", headers={"X-API-Key": created["key"]})
        assert resp.status_code == 403

    def test_valid_key_is_200(self, client, api_key):
        resp = client.get("/api/public/v1/teams", headers={"X-API-Key": api_key})
        assert resp.status_code == 200

    def test_get_only_post_rejected(self, client, api_key):
        resp = client.post("/api/public/v1/teams", headers={"X-API-Key": api_key})
        assert resp.status_code == 405


class TestMetadataDoesNotExposeSecrets:
    def test_no_admin_token_or_key_hashes_in_metadata(self, client, api_key, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.ADMIN_TOKEN", "super-secret-token")
        resp = client.get("/api/public/v1/metadata", headers={"X-API-Key": api_key})
        body = resp.text
        assert "super-secret-token" not in body
        assert api_key not in body
        assert "key_hash" not in body


class TestEnvelopedEndpoints:
    def test_health_envelope_shape(self, client, api_key):
        resp = client.get("/api/public/v1/health", headers={"X-API-Key": api_key})
        data = resp.json()
        assert data["data"]["status"] == "ok"
        assert "generated_at" in data["meta"]
        assert data["meta"]["timezone"] == "America/Lima"

    def test_simulations_latest_not_found_uses_error_envelope(self, client, api_key):
        resp = client.get("/api/public/v1/simulations/latest?model=consensus", headers={"X-API-Key": api_key})
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "not_found"
        assert "consensus" in body["error"]["message"]

    def test_simulations_latest_invalid_model_uses_error_envelope(self, client, api_key):
        resp = client.get("/api/public/v1/simulations/latest?model=nope", headers={"X-API-Key": api_key})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "invalid_model"

    def test_comparison_envelope_shape(self, client, api_key):
        resp = client.get("/api/public/v1/simulations/comparison", headers={"X-API-Key": api_key})
        assert resp.status_code == 200
        body = resp.json()
        assert "models" in body["data"]
        assert "teams" in body["data"]

    def test_bracket_latest_no_run_yet(self, client, api_key):
        resp = client.get("/api/public/v1/bracket/latest?model=consensus", headers={"X-API-Key": api_key})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] is None
        assert body["rounds"] == {}
        assert body["message"]

    def test_bracket_runs_envelope_shape(self, client, api_key):
        resp = client.get("/api/public/v1/bracket/runs?model=consensus", headers={"X-API-Key": api_key})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["model"] == "consensus"
        assert body["data"]["runs"] == []


class TestLegacyAliasesStillWork:
    def test_legacy_simulations_model_name(self, client, api_key):
        resp = client.get("/api/public/v1/simulations/consensus", headers={"X-API-Key": api_key})
        assert resp.status_code == 404
        # legacy shape: flat {"detail": ...}, no {"error": {...}} envelope
        assert "detail" in resp.json()

    def test_legacy_bracket_model_name(self, client, api_key):
        resp = client.get("/api/public/v1/bracket/consensus", headers={"X-API-Key": api_key})
        assert resp.status_code == 404
        assert "detail" in resp.json()

    def test_legacy_teams_and_groups_unchanged(self, client, api_key):
        assert client.get("/api/public/v1/teams", headers={"X-API-Key": api_key}).status_code == 200
        assert client.get("/api/public/v1/groups", headers={"X-API-Key": api_key}).status_code == 200
        assert client.get("/api/public/v1/fixtures", headers={"X-API-Key": api_key}).status_code == 200

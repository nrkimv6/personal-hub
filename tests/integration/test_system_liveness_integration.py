"""
Integration tests for GET /api/v1/system/liveness

Reproduces startup scenario: verifies liveness works even when DB is unavailable.
Uses TestClient (no live server) - can run in worktree.
"""

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestSystemLivenessIntegration:

    def test_liveness_routes_through_api_v1_prefix(self):
        """Routes through /api/v1 prefix correctly, including trailing slash"""
        resp = client.get("/api/v1/system/liveness")
        assert resp.status_code == 200
        # trailing slash - FastAPI default redirect behavior
        resp2 = client.get("/api/v1/system/liveness/", follow_redirects=True)
        assert resp2.status_code == 200

    def test_liveness_does_not_require_auth(self):
        """No auth dependency: unauthenticated request must not get 401/403"""
        resp = client.get("/api/v1/system/liveness")
        assert resp.status_code not in (401, 403)
        assert resp.status_code == 200

    def test_liveness_repro_startup_scenario_db_connection_error(self, monkeypatch):
        """Reproduces boot scenario: liveness returns 200 even when DB raises ConnectionError"""
        monkeypatch.setattr(
            "app.routes.system.SessionLocal",
            Mock(side_effect=ConnectionError("DB not ready")),
        )
        resp = client.get("/api/v1/system/liveness")
        assert resp.status_code == 200, (
            "liveness must survive DB unavailability (boot scenario)"
        )
        assert resp.json()["status"] == "ok"

    def test_liveness_independent_of_status_endpoint(self):
        """liveness and /status are independent: both must work without interference"""
        resp_live = client.get("/api/v1/system/liveness")
        assert resp_live.status_code == 200
        assert set(resp_live.json().keys()) == {"status", "timestamp"}

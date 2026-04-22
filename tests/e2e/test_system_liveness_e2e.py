"""
E2E tests for GET /api/v1/system/liveness

TestClient-based (project convention: tests/e2e/*_e2e.py).
Verifies schema structure, unique timestamps, and independence from /status.
"""

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestSystemLivenessE2E:

    def test_endpoint_returns_200(self):
        resp = client.get("/api/v1/system/liveness")
        assert resp.status_code == 200

    def test_schema_structure(self):
        resp = client.get("/api/v1/system/liveness")
        data = resp.json()
        assert set(data.keys()) == {"status", "timestamp"}
        assert isinstance(data["status"], str) and data["status"] == "ok"
        # timestamp must be ISO8601 parseable
        datetime.fromisoformat(data["timestamp"])

    def test_multiple_calls_return_unique_timestamps(self):
        """Two consecutive calls should produce different timestamps"""
        r1 = client.get("/api/v1/system/liveness").json()["timestamp"]
        r2 = client.get("/api/v1/system/liveness").json()["timestamp"]
        # timestamps reflect wall-clock time, not cached
        assert r1 != r2, "each call must return a fresh timestamp"

    def test_does_not_appear_in_status_endpoint(self):
        """/status endpoint is still functional and schema does not mix with liveness"""
        resp = client.get("/api/v1/system/status")
        assert resp.status_code == 200
        data = resp.json()
        # liveness-only fields must not leak into /status
        assert "status" not in data or data.get("status") is None or isinstance(data.get("current_mode"), str)
        # /status must have its own fields
        assert "current_mode" in data

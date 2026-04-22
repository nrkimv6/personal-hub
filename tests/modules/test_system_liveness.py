"""
Unit tests for GET /api/v1/system/liveness

RIGHT-BICEP + CORRECT based - includes DB/Redis/psutil non-dependency contract tests
"""

import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestGetLiveness:

    def test_get_liveness_R_returns_200_with_status_ok(self):
        """R(Right): normal call returns 200 + status=='ok'"""
        resp = client.get("/api/v1/system/liveness")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_get_liveness_Co_response_contains_iso_timestamp_with_tz(self):
        """Co(Conformance): timestamp is a timezone-aware ISO8601 string"""
        resp = client.get("/api/v1/system/liveness")
        data = resp.json()
        parsed = datetime.fromisoformat(data["timestamp"])
        assert parsed.tzinfo is not None, "timestamp must be timezone-aware"

    def test_get_liveness_E_no_db_session_access(self, monkeypatch):
        """E(Error contract): SessionLocal must never be called by liveness"""
        monkeypatch.setattr(
            "app.routes.system.SessionLocal",
            lambda: pytest.fail("DB must not be touched by liveness"),
        )
        resp = client.get("/api/v1/system/liveness")
        assert resp.status_code == 200

    def test_get_liveness_E_no_redis_access(self, monkeypatch):
        """E(Error contract): WorkerHealthRedis.check must never be called"""
        monkeypatch.setattr(
            "app.routes.system.WorkerHealthRedis.check",
            lambda *a, **kw: pytest.fail("Redis must not be touched"),
        )
        resp = client.get("/api/v1/system/liveness")
        assert resp.status_code == 200

    def test_get_liveness_E_no_psutil_access(self, monkeypatch):
        """E(Error contract): psutil.cpu_percent must never be called"""
        monkeypatch.setattr(
            "app.routes.system.psutil.cpu_percent",
            lambda *a, **kw: pytest.fail("psutil must not be touched"),
        )
        resp = client.get("/api/v1/system/liveness")
        assert resp.status_code == 200

    def test_get_liveness_P_response_under_200ms(self):
        """P(Performance): 10 calls average under 200ms (skip first warmup)"""
        client.get("/api/v1/system/liveness")  # warmup
        times = []
        for _ in range(10):
            start = time.perf_counter()
            client.get("/api/v1/system/liveness")
            times.append(time.perf_counter() - start)
        avg_ms = sum(times) / len(times) * 1000
        assert avg_ms < 200, f"avg response {avg_ms:.1f}ms > 200ms"

    def test_get_liveness_B_schema_rejects_extra_fields(self):
        """B(Boundary): response JSON keys are exactly {status, timestamp}"""
        resp = client.get("/api/v1/system/liveness")
        assert set(resp.json().keys()) == {"status", "timestamp"}

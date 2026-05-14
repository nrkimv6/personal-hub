"""Redis 재시작 API — Podman 소켓 검증 HTTP 통합 테스트

Phase T5 TC:
  - test_POST_redis_restart_socket_fail_returns_cli_guide: podman ps 실패 → 500 + CLI 안내
  - test_POST_redis_restart_socket_ok_proceeds: podman ps 성공 + compose 성공 → 200
"""
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ["TESTING"] = "1"

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class TestRedisRestartSocketCheck:
    """POST /api/v1/system/services/redis/restart — Podman 소켓 검증"""

    def _make_proc(self, returncode: int):
        """asyncio.create_subprocess_exec 반환값 mock."""
        proc = MagicMock()
        proc.returncode = returncode
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    def test_POST_redis_restart_socket_fail_returns_cli_guide(self, client):
        """podman ps 실패 → 500 + detail에 'podman machine stop' CLI 안내 포함"""
        fail_proc = self._make_proc(1)

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=fail_proc,
        ):
            resp = client.post("/api/v1/system/services/redis/restart")

        assert resp.status_code == 500
        detail = resp.json().get("detail", "")
        assert "podman machine stop" in detail

    def test_POST_redis_restart_socket_ok_proceeds(self, client):
        """podman ps 성공 + podman-compose up 성공 → 200 success:true"""
        ok_proc = self._make_proc(0)
        compose_proc = self._make_proc(0)

        procs = [ok_proc, compose_proc]
        call_count = [0]

        async def fake_exec(*args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(procs):
                return procs[idx]
            return ok_proc

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.close.return_value = None

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec), \
             patch("redis.Redis", return_value=mock_redis):
            resp = client.post("/api/v1/system/services/redis/restart")

        assert resp.status_code == 200
        assert resp.json().get("success") is True


class TestRedisStatusHttp:
    """GET /api/v1/system/services/redis — UI status contract."""

    def test_GET_redis_status_connected_false_is_real_disconnected_R(self, client):
        """connected:false JSON is a successful backend status, not a frontend fetch failure."""
        payload = {
            "connected": False,
            "container_running": True,
            "uptime_seconds": None,
            "used_memory_mb": None,
            "connected_clients": None,
        }

        with patch("app.modules.system.routes._redis.get_redis_status", new=AsyncMock(return_value=payload)):
            resp = client.get("/api/v1/system/services/redis")

        assert resp.status_code == 200
        assert resp.json() == payload

    def test_GET_redis_status_connected_true_is_success_payload_R(self, client):
        """connected:true JSON is the success payload that restores the frontend ok state."""
        payload = {
            "connected": True,
            "container_running": True,
            "uptime_seconds": 120,
            "used_memory_mb": 2.5,
            "connected_clients": 1,
        }

        with patch("app.modules.system.routes._redis.get_redis_status", new=AsyncMock(return_value=payload)):
            resp = client.get("/api/v1/system/services/redis")

        assert resp.status_code == 200
        assert resp.json() == payload

    def test_GET_redis_status_failure_returns_http_error_E(self):
        """A backend exception is an HTTP failure, distinct from connected:false JSON."""
        with TestClient(app, raise_server_exceptions=False) as local_client:
            with patch(
                "app.modules.system.routes._redis.get_redis_status",
                new=AsyncMock(side_effect=RuntimeError("redis probe unavailable")),
            ):
                resp = local_client.get("/api/v1/system/services/redis")

        assert resp.status_code == 500

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

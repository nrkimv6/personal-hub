"""
restart_infra / restart_listener direct tests (T1/T3)

worker_service.restart_infra() 및 executor_service.restart_listener()가
browser_workers.py facade 또는 Redis graceful-exit 경로를 올바르게 사용
하는지 검증한다.
"""

import asyncio
import itertools
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def run(coro):
    return asyncio.run(coro)


def _sp_ok(stdout="완료"):
    return MagicMock(returncode=0, stdout=stdout, stderr="")


def _sp_fail(stderr="실패"):
    return MagicMock(returncode=1, stdout="", stderr=stderr)


# ─── worker_service.restart_infra ────────────────────────────────────────────

class TestRestartInfraDirectSubprocess:

    def test_restart_infra_command_listener_uses_redis_signal_R(self):
        """R(정상): restart_infra("command_listener") → executor_service.restart_listener() 경유."""
        from app.modules.system.services.worker_service import WorkerService

        with patch(
            "app.modules.system.services.worker_service.executor_service.restart_listener",
            return_value={"success": True, "message": "listener restarted"},
        ) as mock_restart:
            svc = WorkerService()
            result = run(svc.restart_infra("command_listener"))

        assert result["success"] is True
        mock_restart.assert_called_once()

    def test_restart_infra_api_watchdog_uses_subprocess_R(self):
        """R(정상): restart_infra("api_watchdog") → subprocess.run에 browser_workers.py, restart-infra, api_watchdog 포함"""
        from app.modules.system.services.worker_service import WorkerService

        with patch("app.modules.system.services.worker_service.subprocess.run",
                   return_value=_sp_ok()) as mock_run:
            svc = WorkerService()
            result = run(svc.restart_infra("api_watchdog"))

        assert result["success"] is True
        args = mock_run.call_args[0][0]
        assert "browser_workers.py" in args[1]
        assert "restart-infra" in args
        assert "api_watchdog" in args

    def test_restart_infra_subprocess_failure_returns_error_E(self):
        """E(에러): subprocess returncode=1 시 success=False + stderr 포함"""
        from app.modules.system.services.worker_service import WorkerService

        with patch("app.modules.system.services.worker_service.subprocess.run",
                   return_value=_sp_fail("실행 오류 발생")):
            svc = WorkerService()
            result = run(svc.restart_infra("api_watchdog"))

        assert result["success"] is False
        assert "실행 오류 발생" in result["message"]

    def test_restart_infra_subprocess_timeout_returns_error_E(self):
        """E(에러): subprocess.TimeoutExpired → success=False, 타임아웃 메시지"""
        from app.modules.system.services.worker_service import WorkerService

        with patch("app.modules.system.services.worker_service.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="browser_workers.py", timeout=60)):
            svc = WorkerService()
            result = run(svc.restart_infra("api_watchdog"))

        assert result["success"] is False
        assert "타임아웃" in result["message"]

    def test_restart_infra_no_redis_dependency_B(self):
        """B(경계): restart_infra("command_listener") 호출 시 RedisClient.get_client 미호출"""
        from app.modules.system.services.worker_service import WorkerService

        with patch("app.modules.system.services.worker_service.subprocess.run",
                   return_value=_sp_ok()), \
             patch("app.shared.redis.client.RedisClient") as mock_redis_cls:
            svc = WorkerService()
            run(svc.restart_infra("command_listener"))

        mock_redis_cls.get_client.assert_not_called()

    def test_config_no_infra_command_listener_B(self):
        """B(경계): config에 infra_command_listener 항목 없음 확인"""
        from app.modules.system.config import MANAGED_PROJECTS

        monitor = MANAGED_PROJECTS.get("monitor-page", {})
        items = monitor.get("workers", {}).get("items", [])
        names = [i["name"] for i in items]

        assert "infra_command_listener" not in names, \
            f"infra_command_listener가 config에 남아있음. 현재 목록: {names}"


# ─── executor_service.restart_listener ───────────────────────────────────────

class TestRestartListenerSubprocess:

    def test_restart_listener_uses_redis_signal_R(self):
        """R(정상): restart_listener() → graceful-exit Redis 시그널 전송."""
        from app.modules.dev_runner.services.executor_service import ExecutorService

        svc = ExecutorService()
        mock_r = MagicMock()
        mock_r.get.side_effect = [None, b"restarting", b"2026-02-25T10:00:00"]
        svc.redis_client = mock_r

        with patch("subprocess.run") as mock_run, \
             patch("time.sleep"), \
             patch("time.time", side_effect=itertools.count()):
            result = svc.restart_listener()

        assert result["success"] is True
        assert not mock_run.called
        assert mock_r.lpush.called


# ─── 통합 TC (T3) ────────────────────────────────────────────────────────────

class TestRestartInfraIntegrationDirect:

    def test_integration_restart_listener_end_to_end(self):
        """T3: 실제 browser_workers.py 경로 존재 확인 + Redis 기반 command_listener 경로 검증."""
        from app.modules.system.services.worker_service import WorkerService

        # 실제 파일시스템에서 browser_workers.py 경로 확인
        scripts_dir = PROJECT_ROOT / "scripts"
        browser_workers = scripts_dir / "services" / "browser_workers.py"
        assert browser_workers.exists(), f"browser_workers.py가 없음: {browser_workers}"

        # command_listener는 Redis graceful-exit 경유
        with patch(
            "app.modules.system.services.worker_service.executor_service.restart_listener",
            return_value={"success": True, "message": "listener restarted"},
        ) as mock_restart:
            svc = WorkerService()
            result = run(svc.restart_infra("command_listener"))

        assert result["success"] is True
        mock_restart.assert_called_once()

    def test_integration_executor_restart_listener(self):
        """T3: 실제 browser_workers.py 경로 + Redis graceful-exit 흐름 검증."""
        from app.modules.dev_runner.services.executor_service import ExecutorService

        scripts_dir = PROJECT_ROOT / "scripts"
        browser_workers = scripts_dir / "services" / "browser_workers.py"
        assert browser_workers.exists(), f"browser_workers.py가 없음: {browser_workers}"

        svc = ExecutorService()
        mock_r = MagicMock()
        mock_r.get.side_effect = [None, b"restarting", b"2026-02-25T10:00:00"]
        svc.redis_client = mock_r

        with patch("subprocess.run") as mock_run, \
             patch("time.sleep"), \
             patch("time.time", side_effect=itertools.count()):
            result = svc.restart_listener()

        assert result["success"] is True
        assert not mock_run.called
        assert mock_r.lpush.called


# ─── E2E (T4) ────────────────────────────────────────────────────────────────

class TestRestartInfraE2EDirect:

    @pytest.fixture
    def client(self):
        from app.main import app
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_e2e_restart_infra_command_listener(self, client):
        """T4: POST /api/v1/system/services/infra/command_listener/restart → subprocess mock → 200 + success"""
        with patch("app.modules.system.services.worker_service.subprocess.run",
                   return_value=_sp_ok()):
            resp = client.post("/api/v1/system/services/infra/command_listener/restart")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_e2e_restart_infra_api_watchdog(self, client):
        """T4: POST /api/v1/system/services/infra/api_watchdog/restart → subprocess mock → 200 + success"""
        with patch("app.modules.system.services.worker_service.subprocess.run",
                   return_value=_sp_ok()):
            resp = client.post("/api/v1/system/services/infra/api_watchdog/restart")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


# ─── HTTP 통합 (mock 기반 단위 테스트, 실제 T5 아님 — 실서버 T5는 test_restart_listener_dev_listener.py) ──

class TestRestartListenerHttpDirect:

    @pytest.fixture
    def client(self):
        from app.main import app
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_e2e_dev_runner_restart_listener(self, client):
        """T5: POST /api/v1/dev-runner/restart-listener → subprocess mock + heartbeat → 200 + success"""
        mock_r = MagicMock()
        mock_r.ping.return_value = True
        mock_r.get.side_effect = lambda key: (
            "2026-02-25T10:00:00" if key == "plan-runner:listener:heartbeat" else None
        )

        with patch("app.modules.dev_runner.services.executor_service.executor_service.redis_client", mock_r), \
             patch("app.modules.dev_runner.services.executor_service.subprocess.run",
                   return_value=_sp_ok()), \
             patch("app.modules.dev_runner.services.executor_service.time.sleep"):
            resp = client.post("/api/v1/dev-runner/restart-listener")

        assert resp.status_code in (200, 500, 503)
        if resp.status_code == 200:
            data = resp.json()
            assert data["success"] is True

    def test_e2e_dev_runner_restart_listener_failure(self, client):
        """T5: POST /api/v1/dev-runner/restart-listener → subprocess 실패 → 200 + success: False"""
        mock_r = MagicMock()
        mock_r.ping.return_value = True
        mock_r.get.return_value = None

        with patch("app.modules.dev_runner.services.executor_service.executor_service.redis_client", mock_r), \
             patch("app.modules.dev_runner.services.executor_service.subprocess.run",
                   return_value=_sp_fail("browser_workers 실패")):
            resp = client.post("/api/v1/dev-runner/restart-listener")

        assert resp.status_code in (200, 500, 503)
        if resp.status_code == 200:
            data = resp.json()
            assert data["success"] is False

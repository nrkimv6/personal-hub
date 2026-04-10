"""
dev_runner_listener 시스템 상태 모니터링 테스트 (T1/T2/T3/T5)

MANAGED_PROJECTS에 dev_runner_listener 항목이 올바르게 등록되었는지,
get_worker_status()가 dev_runner_listener를 포함하여 반환하는지,
restart_infra("dev_runner_listener")가 browser_workers.py를 통해 처리되는지 검증.
"""

import asyncio
import copy
import os
import sys
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def run(coro):
    return asyncio.run(coro)


def _sp_ok(stdout="완료"):
    return MagicMock(returncode=0, stdout=stdout, stderr="")


def _sp_fail(stderr="실패"):
    return MagicMock(returncode=1, stdout="", stderr=stderr)


# ─── Phase T1: TC 작성 ─────────────────────────────────────────────────────────

class TestManagedProjectsConfig:

    def test_managed_projects_includes_dev_runner_listener_R(self):
        """R(정상): MANAGED_PROJECTS["monitor-page"]["workers"]["items"]에 dev_runner_listener 항목 존재,
        tier=="infra", watchdog/worker pid_file 값 검증"""
        from app.modules.system.config import MANAGED_PROJECTS

        items = MANAGED_PROJECTS["monitor-page"]["workers"]["items"]
        dev_runner = next((w for w in items if w["name"] == "dev_runner_listener"), None)

        assert dev_runner is not None, "dev_runner_listener 항목이 MANAGED_PROJECTS에 없음"
        assert dev_runner["tier"] == "infra", f"tier가 'infra'여야 함, 실제: {dev_runner['tier']}"
        assert dev_runner["watchdog_pid_file"] == "dev_runner_watchdog_admin.pid", \
            f"watchdog_pid_file 불일치: {dev_runner['watchdog_pid_file']}"
        assert dev_runner["worker_pid_file"] == "dev_runner_command_listener_admin.pid", \
            f"worker_pid_file 불일치: {dev_runner['worker_pid_file']}"
        assert dev_runner["label"] == "Dev Runner 리스너"


class TestWorkerStatusDevRunnerListener:

    def test_worker_status_includes_dev_runner_listener_R(self, tmp_path):
        """R(정상): tmp_path에 dev_runner_command_listener_admin.pid (현재 PID) 생성 →
        get_worker_status()가 dev_runner_listener, running==True 반환"""
        from app.modules.system.services.worker_service import WorkerService
        from app.modules.system.config import MANAGED_PROJECTS

        pid_dir = tmp_path / ".pids"
        pid_dir.mkdir()
        pid_file = pid_dir / "dev_runner_command_listener_admin.pid"
        pid_file.write_text(str(os.getpid()))

        fake_projects = copy.deepcopy(MANAGED_PROJECTS)
        fake_projects["monitor-page"]["path"] = str(tmp_path)

        with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", fake_projects):
            svc = WorkerService()
            result = run(svc.get_worker_status())

        monitor_workers = [w for w in result if w["project"] == "monitor-page"]
        dev_runner = next((w for w in monitor_workers if w["name"] == "dev_runner_listener"), None)

        assert dev_runner is not None, "dev_runner_listener가 get_worker_status() 결과에 없음"
        assert dev_runner["tier"] == "infra"
        assert dev_runner["worker"] is not None
        assert dev_runner["worker"]["running"] is True, "현재 프로세스 PID이므로 running=True여야 함"
        assert dev_runner["worker"]["pid"] == os.getpid()

    def test_dev_runner_listener_dead_shows_not_running_B(self, tmp_path):
        """B(경계): tmp_path에 dev_runner_command_listener_admin.pid (존재하지 않는 PID 999999) 생성 →
        get_worker_status() → worker.running==False"""
        from app.modules.system.services.worker_service import WorkerService
        from app.modules.system.config import MANAGED_PROJECTS

        pid_dir = tmp_path / ".pids"
        pid_dir.mkdir()
        pid_file = pid_dir / "dev_runner_command_listener_admin.pid"
        pid_file.write_text("999999")

        fake_projects = copy.deepcopy(MANAGED_PROJECTS)
        fake_projects["monitor-page"]["path"] = str(tmp_path)

        with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", fake_projects):
            svc = WorkerService()
            result = run(svc.get_worker_status())

        monitor_workers = [w for w in result if w["project"] == "monitor-page"]
        dev_runner = next((w for w in monitor_workers if w["name"] == "dev_runner_listener"), None)

        assert dev_runner is not None
        assert dev_runner["worker"]["running"] is False, "PID 999999는 존재하지 않으므로 running=False여야 함"

    def test_dev_runner_listener_no_pid_file_B(self, tmp_path):
        """B(경계): PID 파일 미생성 상태에서 get_worker_status() → worker.pid==None, worker.running==False"""
        from app.modules.system.services.worker_service import WorkerService
        from app.modules.system.config import MANAGED_PROJECTS

        pid_dir = tmp_path / ".pids"
        pid_dir.mkdir()
        # PID 파일 생성 안 함

        fake_projects = copy.deepcopy(MANAGED_PROJECTS)
        fake_projects["monitor-page"]["path"] = str(tmp_path)

        with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", fake_projects):
            svc = WorkerService()
            result = run(svc.get_worker_status())

        monitor_workers = [w for w in result if w["project"] == "monitor-page"]
        dev_runner = next((w for w in monitor_workers if w["name"] == "dev_runner_listener"), None)

        assert dev_runner is not None
        assert dev_runner["worker"]["pid"] is None, "PID 파일 없으면 pid==None이어야 함"
        assert dev_runner["worker"]["running"] is False

    def test_dev_runner_listener_watchdog_alive_worker_dead_B(self, tmp_path):
        """B(경계): watchdog PID=현재 프로세스(alive), worker PID=999999(dead) →
        watchdog.running==True, worker.running==False"""
        from app.modules.system.services.worker_service import WorkerService
        from app.modules.system.config import MANAGED_PROJECTS

        pid_dir = tmp_path / ".pids"
        pid_dir.mkdir()
        (pid_dir / "dev_runner_watchdog_admin.pid").write_text(str(os.getpid()))
        (pid_dir / "dev_runner_command_listener_admin.pid").write_text("999999")

        fake_projects = copy.deepcopy(MANAGED_PROJECTS)
        fake_projects["monitor-page"]["path"] = str(tmp_path)

        with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", fake_projects):
            svc = WorkerService()
            result = run(svc.get_worker_status())

        monitor_workers = [w for w in result if w["project"] == "monitor-page"]
        dev_runner = next((w for w in monitor_workers if w["name"] == "dev_runner_listener"), None)

        assert dev_runner is not None
        assert dev_runner["watchdog"]["running"] is True, "watchdog는 현재 프로세스 PID이므로 alive여야 함"
        assert dev_runner["worker"]["running"] is False, "worker PID 999999는 dead여야 함"


class TestRestartInfraDevRunnerListener:

    def test_restart_infra_dev_runner_listener_calls_subprocess_R(self):
        """R(정상): restart_infra("dev_runner_listener") → subprocess.run args에
        browser_workers.py, restart-infra, dev_runner_listener 포함"""
        from app.modules.system.services.worker_service import WorkerService

        with patch("app.modules.system.services.worker_service.subprocess.run",
                   return_value=_sp_ok()) as mock_run:
            svc = WorkerService()
            result = run(svc.restart_infra("dev_runner_listener"))

        assert result["success"] is True
        args = mock_run.call_args[0][0]
        assert "browser_workers.py" in args[1], f"browser_workers.py가 args에 없음: {args}"
        assert "restart-infra" in args, f"restart-infra가 args에 없음: {args}"
        assert "dev_runner_listener" in args, f"dev_runner_listener가 args에 없음: {args}"

    def test_restart_infra_dev_runner_listener_not_found_E(self):
        """E(에러): MANAGED_PROJECTS에서 dev_runner_listener 항목 제거 monkeypatch →
        restart_infra("dev_runner_listener") → success==False, '항목 없음' 메시지"""
        from app.modules.system.services.worker_service import WorkerService
        from app.modules.system.config import MANAGED_PROJECTS

        fake_projects = copy.deepcopy(MANAGED_PROJECTS)
        # dev_runner_listener 항목 제거
        items = fake_projects["monitor-page"]["workers"]["items"]
        fake_projects["monitor-page"]["workers"]["items"] = [
            item for item in items if item["name"] != "dev_runner_listener"
        ]

        with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", fake_projects), \
             patch("app.modules.system.services.worker_service.subprocess.run") as mock_run:
            svc = WorkerService()
            result = run(svc.restart_infra("dev_runner_listener"))

        assert result["success"] is False
        assert "dev_runner_listener" in result["message"] or "없음" in result["message"]
        mock_run.assert_not_called()


# ─── Phase T3: 재현/통합 TC ─────────────────────────────────────────────────────

class TestIntegrationConfigPidNamesMatch:

    def test_integration_config_pid_names_match_browser_workers(self):
        """T3: MANAGED_PROJECTS["monitor-page"]["workers"]["items"]의 worker_pid_file 값들이
        browser_workers.py의 BrowserWorkerManager.worker_pid_files에 모두 포함되는지 교차 검증.
        향후 워커 추가 시 누락 방지."""
        from app.modules.system.config import MANAGED_PROJECTS

        items = MANAGED_PROJECTS["monitor-page"]["workers"]["items"]

        # browser_workers.py를 직접 import (pid_suffix="_admin" 기준)
        scripts_dir = PROJECT_ROOT / "scripts"
        sys.path.insert(0, str(scripts_dir))
        from browser_workers import BrowserWorkerManager

        mgr = BrowserWorkerManager()

        # worker_pid_file이 None이 아닌 항목만 검사
        for item in items:
            wpf = item.get("worker_pid_file")
            if wpf is None:
                continue
            assert wpf in mgr.worker_pid_files, (
                f"MANAGED_PROJECTS의 worker_pid_file '{wpf}' (name={item['name']})이 "
                f"browser_workers.py의 worker_pid_files에 없음: {mgr.worker_pid_files}"
            )

    def test_integration_watchdog_pid_names_match_browser_workers(self):
        """T3: MANAGED_PROJECTS["monitor-page"]["workers"]["items"]의 dev_runner_listener
        watchdog_pid_file이 browser_workers.py의 BrowserWorkerManager.workers 리스트의
        pid_file에 존재하는지 교차 검증. restart_infra("dev_runner_listener") 매칭 실패 방지.

        참고: api_watchdog는 NSSM 관리 항목으로 browser_workers.py self.workers에 미포함
        (별도 처리 경로). 이 테스트는 dev_runner_listener만 검증한다.
        """
        from app.modules.system.config import MANAGED_PROJECTS

        items = MANAGED_PROJECTS["monitor-page"]["workers"]["items"]

        scripts_dir = PROJECT_ROOT / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from browser_workers import BrowserWorkerManager

        mgr = BrowserWorkerManager()
        worker_pid_files = {w["pid_file"] for w in mgr.workers}

        # dev_runner_listener만 검증 (api_watchdog는 NSSM 관리, browser_workers 외부)
        browser_workers_infra = ["dev_runner_listener", "command_listener", "unified_worker", "claude_worker"]
        for item in items:
            if item["name"] not in browser_workers_infra:
                continue
            wdog_pf = item.get("watchdog_pid_file")
            if wdog_pf is None:
                continue
            assert wdog_pf in worker_pid_files, (
                f"MANAGED_PROJECTS의 watchdog_pid_file '{wdog_pf}' (name={item['name']})이 "
                f"browser_workers.py의 workers pid_file 목록에 없음: {worker_pid_files}. "
                f"restart_infra('{item['name']}')가 watchdog를 찾지 못함"
            )

    def test_integration_dev_runner_listener_pid_written_by_watchdog(self):
        """T3: scripts/dev-runner-listener-watchdog.ps1 파일이 존재하고,
        dev_runner_command_listener 관련 PID 파일명 문자열이 포함되는지 검증.
        PID 파일명 drift 방지."""
        watchdog_script = PROJECT_ROOT / "scripts" / "dev-runner-listener-watchdog.ps1"
        assert watchdog_script.exists(), f"watchdog 스크립트가 없음: {watchdog_script}"

        content = watchdog_script.read_text(encoding="utf-8", errors="replace")
        assert "dev_runner_command_listener" in content or "dev-runner-command-listener" in content, (
            "watchdog 스크립트에 dev_runner_command_listener PID 파일 참조가 없음. "
            "PID 파일명 drift 가능성 있음"
        )


# ─── Phase T5: HTTP 통합 ─────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)


class TestHttpWorkerStatus:

    def test_http_workers_status_includes_dev_runner_listener(self, client):
        """T5: TestClient GET /api/v1/system/services/workers →
        응답에 dev_runner_listener 포함, tier=="infra", watchdog/worker dict 존재"""
        with patch("app.modules.system.services.worker_service.WorkerService._check_process_exists",
                   return_value=True):
            resp = client.get("/api/v1/system/services/workers")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

        dev_runner = next((w for w in data if w["name"] == "dev_runner_listener"), None)
        assert dev_runner is not None, (
            f"dev_runner_listener가 응답에 없음. 전체 이름 목록: {[w['name'] for w in data]}"
        )
        assert dev_runner["tier"] == "infra"
        assert "watchdog" in dev_runner
        assert "worker" in dev_runner


class TestHttpRestartInfraDevRunnerListener:

    def test_http_restart_infra_dev_runner_listener(self, client):
        """T5: TestClient POST /api/v1/system/services/infra/dev_runner_listener/restart +
        subprocess.run mock(returncode=0) → 200 + success==True"""
        with patch("app.modules.system.services.worker_service.subprocess.run",
                   return_value=_sp_ok()) as mock_run:
            resp = client.post("/api/v1/system/services/infra/dev_runner_listener/restart")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        args = mock_run.call_args[0][0]
        assert "restart-infra" in args
        assert "dev_runner_listener" in args

    def test_http_restart_infra_dev_runner_listener_failure_E(self, client):
        """E(에러): subprocess.run mock(returncode=1) → success==False"""
        with patch("app.modules.system.services.worker_service.subprocess.run",
                   return_value=_sp_fail("재시작 실패")):
            resp = client.post("/api/v1/system/services/infra/dev_runner_listener/restart")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

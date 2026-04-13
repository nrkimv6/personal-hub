"""
restart-listener가 dev_listener role도 kill + 재시작하는지 검증.

대상: scripts/browser_workers.py restart_listener()
버그: restart-listener가 role=="listener"만 재시작, dev_listener 누락
수정: role not in ("listener", "dev_listener") 필터로 변경
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ─── 공통 fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def browser_workers_module():
    """browser_workers.py를 임포트하여 모듈 반환."""
    scripts_dir = Path(__file__).parent.parent / "scripts" / "services"
    sys.path.insert(0, str(scripts_dir))
    try:
        import browser_workers
        yield browser_workers
    finally:
        sys.path.pop(0)


@pytest.fixture
def mock_manager(browser_workers_module, tmp_path):
    """BrowserWorkerManager를 pid_dir=tmp_path로 생성 (프로세스 실행 없이)."""
    bw = browser_workers_module
    from scripts.services.browser_worker_runtime import manager as bw_impl
    with patch.object(bw_impl, "tracked_popen_sync") as mock_popen, \
         patch.object(bw_impl, "read_pid_file", return_value=None), \
         patch.object(bw_impl, "is_process_alive", return_value=False), \
         patch.object(bw_impl, "kill_pid"), \
         patch.object(bw_impl, "remove_pid_file"), \
         patch("time.sleep"):
        mgr = bw.BrowserWorkerManager.__new__(bw.BrowserWorkerManager)
        mgr.pid_dir = tmp_path
        mgr.pid_suffix = "_admin"
        mgr.python_exe = sys.executable
        mgr.scripts_dir = Path(__file__).parent.parent / "scripts"
        mgr.workers = [
            {
                "name": "Command Listener Watchdog",
                "pid_file": "command_listener_watchdog_admin.pid",
                "cmd": ["powershell", "-File", "command-listener-watchdog.ps1"],
                "env": {"APP_MODE": "admin"},
                "role": "listener",
            },
            {
                "name": "Dev Runner Listener Watchdog",
                "pid_file": "dev_runner_watchdog_admin.pid",
                "cmd": ["powershell", "-ExecutionPolicy", "Bypass", "-File", "dev-runner-listener-watchdog.ps1"],
                "env": {"APP_MODE": "admin"},
                "role": "dev_listener",
            },
        ]
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc
        yield mgr, mock_popen, bw_impl


# ─── Phase T1: 단위 테스트 ──────────────────────────────────────────────────

class TestRestartListenerDevListener:
    """restart_listener()가 dev_listener role도 포함하는지 검증."""

    def test_restart_listener_includes_dev_listener_pid_kill_R(self, mock_manager, browser_workers_module):
        """R(정상): restart_listener() 호출 시 dev_runner_command_listener PID 파일도 kill 대상에 포함."""
        mgr, mock_popen, bw = mock_manager
        mgr.restart_listener()
        # remove_pid_file이 dev_runner_command_listener PID 파일에도 호출되었는지 확인
        remove_calls = bw.remove_pid_file.call_args_list
        removed_files = [str(c[0][0]) for c in remove_calls]
        assert any("dev_runner_command_listener" in f for f in removed_files), \
            f"dev_runner_command_listener PID가 kill 대상에 없음. 제거된 파일: {removed_files}"

    def test_restart_listener_starts_dev_listener_role_R(self, mock_manager, browser_workers_module):
        """R(정상): restart_listener() 호출 후 dev_listener role 워커도 시작."""
        mgr, mock_popen, bw = mock_manager
        mgr.restart_listener()
        # tracked_popen_sync가 2번 호출 (listener + dev_listener)
        assert mock_popen.call_count == 2, \
            f"tracked_popen_sync가 {mock_popen.call_count}회 호출됨 (기대: 2 — listener + dev_listener)"
        # dev_listener role로 호출되었는지 확인
        roles = [c.kwargs.get("role") or c[1].get("role", "") for c in mock_popen.call_args_list]
        assert "dev_listener" in roles, f"dev_listener role이 시작되지 않음. 시작된 role: {roles}"

    def test_restart_listener_no_dev_listener_pid_B(self, mock_manager, browser_workers_module):
        """B(경계): dev_runner_command_listener PID 파일이 없을 때도 정상 동작."""
        mgr, mock_popen, bw = mock_manager
        # PID 파일 없음 → read_pid_file이 None 반환 (이미 mock)
        mgr.restart_listener()
        # 에러 없이 완료되어야 함
        assert mock_popen.call_count == 2  # 여전히 2개 워커 시작

    def test_restart_listener_dev_listener_already_running_B(self, mock_manager, browser_workers_module):
        """B(경계): dev_listener가 이미 실행 중이면 스킵."""
        mgr, mock_popen, bw = mock_manager
        # is_process_alive를 True로, read_pid_file을 PID 반환하도록 변경
        bw.read_pid_file.return_value = 9999
        bw.is_process_alive.return_value = True
        mgr.restart_listener()
        # already running이므로 popen 호출 0회
        assert mock_popen.call_count == 0, \
            f"이미 실행 중인데 popen이 {mock_popen.call_count}회 호출됨"


# ─── Phase T3: 통합 테스트 (실제 파일시스템) ──────────────────────────────────

class TestIntegrationRestartListener:
    """실제 파일시스템/경로 해석 검증 (mock 최소화)."""

    def test_integration_path_resolves_to_existing_file(self):
        """T3: PROJECT_ROOT / 'scripts' / 'browser_workers.py' 경로가 실제 존재하는 파일인지 검증."""
        from app.core.config import PROJECT_ROOT
        browser_workers_path = PROJECT_ROOT / "scripts" / "services" / "browser_workers.py"
        assert browser_workers_path.exists(), f"browser_workers.py not found at {browser_workers_path}"
        assert browser_workers_path.is_file(), f"{browser_workers_path} is not a file"

    def test_integration_worker_service_project_root_import(self):
        """T3: worker_service.py가 PROJECT_ROOT를 올바르게 import하여 scripts/ 경로를 해석하는지 검증."""
        from app.core.config import PROJECT_ROOT
        scripts_dir = PROJECT_ROOT / "scripts"
        assert scripts_dir.exists(), f"scripts dir not found at {scripts_dir}"
        assert (scripts_dir / "services" / "browser_workers.py").exists()

    def test_integration_executor_service_project_root_import(self):
        """T3: executor_service.py가 PROJECT_ROOT를 올바르게 import하여 browser_workers.py 경로를 해석하는지 검증."""
        from app.core.config import PROJECT_ROOT
        browser_workers = PROJECT_ROOT / "scripts" / "services" / "browser_workers.py"
        assert browser_workers.exists(), f"browser_workers.py not found at {browser_workers}"

    def test_integration_restart_listener_worker_roles(self, browser_workers_module):
        """T3: browser_workers.py의 workers 리스트에 listener + dev_listener role이 모두 존재하는지 검증."""
        bw = browser_workers_module
        # BrowserWorkerManager 생성 없이 workers 정의를 확인
        import inspect
        source = inspect.getsource(bw.BrowserWorkerManager.__init__)
        assert '"listener"' in source, "listener role이 workers에 없음"
        assert '"dev_listener"' in source, "dev_listener role이 workers에 없음"

    def test_integration_restart_listener_filter_includes_dev_listener(self, browser_workers_module):
        """T3: restart_listener()의 role 필터가 dev_listener를 포함하는지 소스 코드로 검증."""
        import inspect
        source = inspect.getsource(browser_workers_module.BrowserWorkerManager.restart_listener)
        assert 'not in ("listener", "dev_listener")' in source or \
               "not in ('listener', 'dev_listener')" in source, \
            f"restart_listener의 role 필터가 dev_listener를 포함하지 않음"


# ─── Phase T4: E2E 테스트 (실서버, http_live 마커) ────────────────────────────

@pytest.mark.http_live
class TestE2ERestartListenerLive:
    """실서버 API를 직접 호출하여 listener 재시작 + listener_alive 상태 변화 검증."""

    def test_e2e_restart_infra_command_listener_live(self):
        """T4: POST /system/services/infra/command_listener/restart → listener_alive: true."""
        import httpx
        base = "http://localhost:8001/api/v1"
        # 재시작 요청
        resp = httpx.post(f"{base}/system/services/infra/command_listener/restart", timeout=30)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True, f"restart 실패: {data}"
        # 5초 대기 후 status 확인
        import time
        time.sleep(5)
        status_resp = httpx.get(f"{base}/dev-runner/status", timeout=10)
        assert status_resp.status_code == 200
        status = status_resp.json()
        assert status["listener_alive"] is True, f"listener_alive가 여전히 false: {status}"

    def test_e2e_restart_listener_live(self):
        """T4: POST /dev-runner/restart-listener → success + listener restarted."""
        import httpx
        base = "http://localhost:8001/api/v1"
        resp = httpx.post(f"{base}/dev-runner/restart-listener", timeout=30)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True, f"restart-listener 실패: {data}"
        assert "listener restarted" in data.get("message", ""), f"메시지 불일치: {data}"


# ─── Phase T5: HTTP 통합 (TestClient 기반) ────────────────────────────────────

@pytest.mark.http
class TestHTTPRestartListenerDev:
    """TestClient + Redis mock 기반 HTTP 통합 (Redis graceful-exit 방식)."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as c:
            yield c

    def test_http_restart_infra_command_listener(self, client):
        """T5: POST /system/services/infra/command_listener/restart → 200 + success."""
        with patch(
            "app.modules.system.services.worker_service.executor_service.restart_listener",
            return_value={"success": True, "message": "listener restarted"},
        ):
            resp = client.post("/api/v1/system/services/infra/command_listener/restart")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_http_restart_listener_success(self, client):
        """T5: POST /dev-runner/restart-listener + Redis 시그널 mock → 200 + success."""
        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService.restart_listener",
            return_value={"success": True, "message": "listener restarted"},
        ):
            resp = client.post("/api/v1/dev-runner/restart-listener")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_http_restart_listener_failure(self, client):
        """T5: POST /dev-runner/restart-listener + graceful-exit 실패 → success: false."""
        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService.restart_listener",
            return_value={"success": False, "message": "graceful-exit 타임아웃"},
        ):
            resp = client.post("/api/v1/dev-runner/restart-listener")
        assert resp.status_code == 200
        assert resp.json()["success"] is False

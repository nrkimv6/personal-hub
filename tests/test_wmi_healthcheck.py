"""
tests/test_wmi_healthcheck.py — browser_workers 핵심 동작 단위 테스트
"""

import io
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# scripts 디렉토리를 경로에 추가 (browser_workers, service_utils 이동: scripts/ → scripts/services/)
_scripts_dir = os.path.join(os.path.dirname(__file__), "..", "scripts")
_services_dir = os.path.join(_scripts_dir, "services")
sys.path.insert(0, _scripts_dir)
sys.path.insert(0, _services_dir)

import browser_workers
import service_utils
from browser_workers import BrowserWorkerManager


class _Response:
    def __init__(self, status: int = 200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _make_manager(tmp_path: Path) -> BrowserWorkerManager:
    """BrowserWorkerManager 인스턴스 생성 (초기화 부작용 없이)."""
    mgr = object.__new__(BrowserWorkerManager)
    mgr.pid_dir = tmp_path / ".pids"
    mgr.log_dir = tmp_path / "logs" / "admin"
    mgr.scripts_dir = tmp_path / "scripts"
    mgr.frontend_dir = tmp_path / "frontend"
    mgr.pid_dir.mkdir(parents=True, exist_ok=True)
    mgr.log_dir.mkdir(parents=True, exist_ok=True)
    mgr.scripts_dir.mkdir(parents=True, exist_ok=True)
    mgr.frontend_dir.mkdir(parents=True, exist_ok=True)

    mgr.pid_suffix = "_admin"
    mgr.api_port = 8001
    mgr.frontend_port = 6101
    mgr.frontend_restart_lock = mgr.pid_dir / "frontend_restart.lock"

    # status()에서 참조되는 필드
    mgr.workers = []
    mgr.worker_pid_files = []
    mgr.legacy_pid_files = []
    return mgr


class TestCheckWmiHealth:
    def test_check_wmi_health_success(self, tmp_path):
        """WMI 정상 시 (returncode=0) True 반환."""
        mgr = _make_manager(tmp_path)

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = mgr._check_wmi_health()

        assert result is True
        mock_run.assert_called_once_with(
            ["python", "-c", "import platform; platform.machine()"],
            timeout=5,
            capture_output=True,
        )

    def test_check_wmi_health_timeout(self, tmp_path):
        """subprocess.TimeoutExpired 발생 시 False 반환."""
        mgr = _make_manager(tmp_path)

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="python", timeout=5)):
            result = mgr._check_wmi_health()

        assert result is False


class TestFixWmi:
    def test_fix_wmi_calls_powershell(self, tmp_path):
        """_fix_wmi()가 Restart-Service winmgmt -Force 명령을 호출하는지 확인."""
        mgr = _make_manager(tmp_path)

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = mgr._fix_wmi()

        assert result is True
        mock_run.assert_called_once_with(
            ["powershell", "-Command", "Restart-Service winmgmt -Force"],
            timeout=15,
            capture_output=True,
        )


class TestRestartFrontendCliArgs:
    def test_restart_frontend_mode_right_default_admin(self, monkeypatch):
        """R: restart-frontend 기본 호출은 admin 모드."""
        mgr = MagicMock()
        mgr.restart_frontend.return_value = True
        monkeypatch.setattr(browser_workers, "BrowserWorkerManager", lambda: mgr)
        monkeypatch.setattr(sys, "argv", ["browser_workers.py", "restart-frontend"])

        with pytest.raises(SystemExit) as exc:
            browser_workers.main()

        assert exc.value.code == 0
        mgr.restart_frontend.assert_called_once_with(public=False)

    def test_restart_frontend_mode_right_public_flag(self, monkeypatch):
        """R: --public 전달 시 public 모드."""
        mgr = MagicMock()
        mgr.restart_frontend.return_value = True
        monkeypatch.setattr(browser_workers, "BrowserWorkerManager", lambda: mgr)
        monkeypatch.setattr(sys, "argv", ["browser_workers.py", "restart-frontend", "--public"])

        with pytest.raises(SystemExit) as exc:
            browser_workers.main()

        assert exc.value.code == 0
        mgr.restart_frontend.assert_called_once_with(public=True)

    def test_restart_frontend_mode_error_invalid_combo(self, monkeypatch, capsys):
        """E: status + --public 조합은 에러."""
        monkeypatch.setattr(sys, "argv", ["browser_workers.py", "status", "--public"])

        with pytest.raises(SystemExit) as exc:
            browser_workers.main()

        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "--public can only be used with restart-frontend" in captured.err

    def test_restart_frontend_mode_boundary_legacy_option_hint(self, monkeypatch):
        """B: --restart-frontend 오입력 시 교정 힌트 반환."""
        stderr = io.StringIO()
        monkeypatch.setattr(sys, "argv", ["browser_workers.py", "--restart-frontend"])
        with patch("sys.stderr", stderr):
            with pytest.raises(SystemExit) as exc:
                browser_workers.main()

        assert exc.value.code == 2
        assert "Use positional action" in stderr.getvalue()


class TestRestartFrontendBehavior:
    def test_restart_frontend_dev_right_runs_npm_dev(self, tmp_path):
        """R: admin 모드에서 npm run dev 호출."""
        mgr = _make_manager(tmp_path)
        mock_proc = MagicMock()
        mock_proc.pid = 4321

        with patch.object(mgr, "_acquire_frontend_restart_lock", return_value=100), patch.object(
            mgr, "_release_frontend_restart_lock"
        ), patch.object(mgr, "_cleanup_frontend_runtime"), patch.object(mgr, "_prepare_frontend_env"), patch.object(
            mgr, "_run_frontend_build_if_needed", return_value=True
        ), patch.object(
            mgr, "_has_port_collision_error", return_value=False
        ), patch(
            "browser_workers.tracked_popen_sync", return_value=mock_proc
        ) as mock_popen, patch(
            "browser_workers.pick_listener_pid", side_effect=[1111, 2222]
        ), patch(
            "browser_workers.time.sleep", return_value=None
        ), patch(
            "browser_workers.urllib.request.urlopen", return_value=_Response(200)
        ), patch(
            "browser_workers.write_pid_file"
        ):
            ok = mgr.restart_frontend(public=False)

        assert ok is True
        cmd = mock_popen.call_args.args[0]
        assert cmd[:3] == ["npm.cmd", "run", "dev"]
        assert "--port" in cmd
        assert "6101" in cmd

    def test_restart_frontend_public_right_runs_build_preview(self, tmp_path):
        """R: public 모드에서 preview 실행."""
        mgr = _make_manager(tmp_path)
        mock_proc = MagicMock()
        mock_proc.pid = 9876

        with patch.object(mgr, "_acquire_frontend_restart_lock", return_value=101), patch.object(
            mgr, "_release_frontend_restart_lock"
        ), patch.object(mgr, "_cleanup_frontend_runtime"), patch.object(mgr, "_prepare_frontend_env"), patch.object(
            mgr, "_run_frontend_build_if_needed", return_value=True
        ) as mock_build, patch.object(
            mgr, "_has_port_collision_error", return_value=False
        ), patch(
            "browser_workers.tracked_popen_sync", return_value=mock_proc
        ) as mock_popen, patch(
            "browser_workers.pick_listener_pid", side_effect=[None, 3333]
        ), patch(
            "browser_workers.time.sleep", return_value=None
        ), patch(
            "browser_workers.urllib.request.urlopen", return_value=_Response(200)
        ), patch(
            "browser_workers.write_pid_file"
        ):
            ok = mgr.restart_frontend(public=True)

        assert ok is True
        assert mock_build.called
        cmd = mock_popen.call_args.args[0]
        assert cmd[:3] == ["npm.cmd", "run", "preview"]
        assert "--port" in cmd
        assert "6100" in cmd

    def test_restart_frontend_public_error_build_fail_without_artifact(self, tmp_path):
        """E: build 실패 + 아티팩트 없음이면 재시작 실패."""
        mgr = _make_manager(tmp_path)

        with patch.object(mgr, "_acquire_frontend_restart_lock", return_value=102), patch.object(
            mgr, "_release_frontend_restart_lock"
        ), patch.object(mgr, "_cleanup_frontend_runtime"), patch.object(mgr, "_prepare_frontend_env"), patch.object(
            mgr, "_run_frontend_build_if_needed", return_value=False
        ), patch(
            "browser_workers.tracked_popen_sync"
        ) as mock_popen, patch(
            "browser_workers.time.sleep", return_value=None
        ):
            ok = mgr.restart_frontend(public=True)

        assert ok is False
        mock_popen.assert_not_called()

    def test_restart_frontend_public_boundary_build_fail_with_artifact_fallback(self, tmp_path):
        """B: build 실패 + 기존 build/ 존재 시 fallback 허용."""
        mgr = _make_manager(tmp_path)
        (mgr.frontend_dir / "build").mkdir(parents=True, exist_ok=True)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "build failed"
        mock_result.stdout = ""

        with patch("browser_workers.subprocess.run", return_value=mock_result):
            assert mgr._run_frontend_build_if_needed(public=True) is True

    def test_restart_frontend_error_port_in_use_not_success(self, tmp_path):
        """E: Port already in use 감지 시 성공 판정 금지."""
        mgr = _make_manager(tmp_path)
        mock_proc = MagicMock()
        mock_proc.pid = 3131

        with patch.object(mgr, "_acquire_frontend_restart_lock", return_value=103), patch.object(
            mgr, "_release_frontend_restart_lock"
        ), patch.object(mgr, "_cleanup_frontend_runtime"), patch.object(mgr, "_prepare_frontend_env"), patch.object(
            mgr, "_run_frontend_build_if_needed", return_value=True
        ), patch.object(
            mgr, "_has_port_collision_error", return_value=True
        ), patch(
            "browser_workers.tracked_popen_sync", return_value=mock_proc
        ), patch(
            "browser_workers.pick_listener_pid", side_effect=[1234, 5678]
        ), patch(
            "browser_workers.time.sleep", return_value=None
        ), patch(
            "browser_workers.urllib.request.urlopen", return_value=_Response(200)
        ) as mock_urlopen:
            ok = mgr.restart_frontend(public=False)

        assert ok is False
        mock_urlopen.assert_not_called()


class TestListenerPidAndStatus:
    def test_pick_listener_pid_right_single_listener(self):
        """R: listener PID 1개일 때 그대로 반환."""
        with patch("service_utils.find_pids_on_port", return_value=[4444]):
            assert service_utils.pick_listener_pid(6101) == 4444

    def test_pick_listener_pid_boundary_multiple_listeners(self):
        """B: 다중 PID에서 우선순위(세션/프로세스명/시각)대로 선택."""
        proc1 = MagicMock()
        proc1.name.return_value = "python.exe"
        proc1.create_time.return_value = 100.0

        proc2 = MagicMock()
        proc2.name.return_value = "node.exe"
        proc2.create_time.return_value = 200.0

        with patch("service_utils.find_pids_on_port", return_value=[11, 22]), patch(
            "service_utils.get_session_id", side_effect=[1, 1, 1]
        ), patch("service_utils.psutil.Process", side_effect=[proc1, proc2]):
            assert service_utils.pick_listener_pid(6101) == 22

    def test_status_autoheal_pidfile_stale_right(self, tmp_path):
        """R: stale PID 감지 시 listener PID로 자동 보정."""
        mgr = _make_manager(tmp_path)
        admin_pid_file = mgr.pid_dir / "frontend_admin.pid"

        with patch.object(mgr, "_print_redis_status"), patch(
            "browser_workers.read_pid_file", return_value=None
        ), patch(
            "browser_workers.is_port_listening", side_effect=[True, False]
        ), patch(
            "browser_workers.pick_listener_pid", return_value=7777
        ), patch(
            "browser_workers.write_pid_file"
        ) as mock_write:
            mgr.status()

        mock_write.assert_called_once_with(admin_pid_file, 7777)

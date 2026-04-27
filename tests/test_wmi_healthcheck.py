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
from scripts.services import frontend_mode
from scripts.services.browser_worker_runtime import frontend_actions
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


def _prepare_frontend_runtime_files(frontend_dir: Path) -> None:
    vite_bin = frontend_dir / "node_modules" / ".bin" / "vite.cmd"
    vite_bin.parent.mkdir(parents=True, exist_ok=True)
    vite_bin.write_text("@echo off\r\n", encoding="utf-8")

    base_tsconfig = frontend_dir / ".svelte-kit" / "tsconfig.json"
    base_tsconfig.parent.mkdir(parents=True, exist_ok=True)
    base_tsconfig.write_text("{\"compilerOptions\":{}}", encoding="utf-8")


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

    @pytest.mark.parametrize(("argv", "public"), [
        (["browser_workers.py", "restart-frontend"], False),
        (["browser_workers.py", "restart-frontend", "--public"], True),
    ])
    def test_restart_frontend_mode_error_failure_returns_exit_one(self, monkeypatch, argv, public):
        """E: restart 실패는 admin/public 모두 exit 1이어야 한다."""
        mgr = MagicMock()
        mgr.restart_frontend.return_value = False
        monkeypatch.setattr(browser_workers, "BrowserWorkerManager", lambda: mgr)
        monkeypatch.setattr(sys, "argv", argv)

        with pytest.raises(SystemExit) as exc:
            browser_workers.main()

        assert exc.value.code == 1
        mgr.restart_frontend.assert_called_once_with(public=public)

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
    def test_reset_frontend_runtime_types_clears_types_only_right(self, tmp_path):
        """R: runtime types만 비우고 tsconfig는 유지한다."""
        mgr = _make_manager(tmp_path)
        runtime_outdir = mgr.frontend_dir / ".svelte-kit-admin"
        runtime_types = runtime_outdir / "types" / "src" / "routes"
        runtime_types.mkdir(parents=True, exist_ok=True)
        (runtime_outdir / "tsconfig.json").write_text("{\"compilerOptions\":{}}", encoding="utf-8")
        (runtime_types / "proxy+page.server.ts").write_text("// generated", encoding="utf-8")

        frontend_actions._reset_frontend_runtime_types(mgr, public=False)

        assert (runtime_outdir / "tsconfig.json").exists()
        assert not (runtime_outdir / "types").exists()

    def test_restart_frontend_waits_for_release_and_clears_types_before_start_boundary(self, tmp_path):
        """B: 재시작 전에 이전 frontend 종료 대기와 runtime types 정리를 수행한다."""
        mgr = _make_manager(tmp_path)
        mock_proc = MagicMock()
        mock_proc.pid = 4321
        call_order: list[str] = []

        def _record(name: str):
            def _inner(*args, **kwargs):
                call_order.append(name)
                return None

            return _inner

        with patch.object(mgr, "_acquire_frontend_restart_lock", return_value=100), patch.object(
            mgr, "_release_frontend_restart_lock"
        ), patch.object(
            mgr, "_cleanup_frontend_runtime", side_effect=lambda *args, **kwargs: [1111, 2222]
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions._wait_for_terminated_pids",
            side_effect=lambda pids, timeout_seconds=15.0: call_order.append(f"wait:{','.join(str(pid) for pid in pids)}")
            or True,
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions._reset_frontend_runtime_types",
            side_effect=lambda manager, public: call_order.append(f"reset:{public}"),
        ), patch.object(
            mgr, "_prepare_frontend_env", side_effect=_record("prepare")
        ), patch.object(
            mgr, "_run_frontend_build_if_needed", return_value=True
        ), patch.object(
            mgr, "_has_port_collision_error", return_value=False
        ), patch(
            "scripts.services.browser_worker_runtime.manager.tracked_popen_sync", return_value=mock_proc
        ), patch(
            "scripts.services.browser_worker_runtime.manager.pick_listener_pid", return_value=1234
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions._wait_for_frontend_listener", return_value=5678
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions._wait_for_frontend_http_ready",
            return_value=(True, None),
        ), patch(
            "scripts.services.browser_worker_runtime.manager.time.sleep", return_value=None
        ), patch(
            "scripts.services.browser_worker_runtime.manager.write_pid_file"
        ):
            ok = mgr.restart_frontend(public=False)

        assert ok is True
        assert call_order[:3] == ["wait:1111,2222", "reset:False", "prepare"]

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
            "scripts.services.browser_worker_runtime.manager.tracked_popen_sync", return_value=mock_proc
        ) as mock_popen, patch(
            "scripts.services.browser_worker_runtime.manager.pick_listener_pid", return_value=1111
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions._wait_for_frontend_listener", return_value=2222
        ), patch(
            "scripts.services.browser_worker_runtime.manager.time.sleep", return_value=None
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions._wait_for_frontend_http_ready",
            return_value=(True, None),
        ), patch(
            "scripts.services.browser_worker_runtime.manager.write_pid_file"
        ):
            ok = mgr.restart_frontend(public=False)

        assert ok is True
        cmd = mock_popen.call_args.args[0]
        assert cmd[:3] == ["npm.cmd", "run", "dev"]
        assert "--port" in cmd
        assert "6101" in cmd
        env = mock_popen.call_args.kwargs["env"]
        assert env["MONITOR_FRONTEND_MODE"] == "admin"
        assert env["MONITOR_SVELTEKIT_OUTDIR"] == ".svelte-kit-admin"
        assert env["VITE_API_PORT"] == "8001"

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
            "scripts.services.browser_worker_runtime.manager.tracked_popen_sync", return_value=mock_proc
        ) as mock_popen, patch(
            "scripts.services.browser_worker_runtime.manager.pick_listener_pid", return_value=None
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions._wait_for_frontend_listener", return_value=3333
        ), patch(
            "scripts.services.browser_worker_runtime.manager.time.sleep", return_value=None
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions._wait_for_frontend_http_ready",
            return_value=(True, None),
        ), patch(
            "scripts.services.browser_worker_runtime.manager.write_pid_file"
        ):
            ok = mgr.restart_frontend(public=True)

        assert ok is True
        assert mock_build.called
        cmd = mock_popen.call_args.args[0]
        assert cmd[:3] == ["npm.cmd", "run", "preview"]
        assert "--port" in cmd
        assert "6100" in cmd
        env = mock_popen.call_args.kwargs["env"]
        assert env["MONITOR_FRONTEND_MODE"] == "public"
        assert env["MONITOR_SVELTEKIT_OUTDIR"] == ".svelte-kit-public"
        assert "VITE_API_PORT" not in env

    def test_run_frontend_build_if_needed_public_right_passes_runtime_env(self, tmp_path):
        """R: public build 단계도 runtime contract env를 사용한다."""
        mgr = _make_manager(tmp_path)
        frontend_env = mgr._frontend_runtime_env(public=True)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = ""

        with patch(
            "scripts.services.browser_worker_runtime.frontend_actions.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            ok = mgr._run_frontend_build_if_needed(public=True, frontend_env=frontend_env)

        assert ok is True
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["env"]["MONITOR_FRONTEND_MODE"] == "public"
        assert call_kwargs["env"]["MONITOR_SVELTEKIT_OUTDIR"] == ".svelte-kit-public"
        assert "VITE_API_PORT" not in call_kwargs["env"]

    def test_restart_frontend_public_error_build_fail_without_artifact(self, tmp_path):
        """E: build 실패 + 아티팩트 없음이면 재시작 실패."""
        mgr = _make_manager(tmp_path)

        with patch.object(mgr, "_acquire_frontend_restart_lock", return_value=102), patch.object(
            mgr, "_release_frontend_restart_lock"
        ), patch.object(mgr, "_cleanup_frontend_runtime"), patch.object(mgr, "_prepare_frontend_env"), patch.object(
            mgr, "_run_frontend_build_if_needed", return_value=False
        ), patch(
            "scripts.services.browser_worker_runtime.manager.tracked_popen_sync"
        ) as mock_popen, patch(
            "scripts.services.browser_worker_runtime.manager.time.sleep", return_value=None
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

        with patch("scripts.services.browser_worker_runtime.manager.subprocess.run", return_value=mock_result):
            assert mgr._run_frontend_build_if_needed(public=True) is True

    def test_restart_frontend_public_build_failure_writes_shared_build_log_right(self, tmp_path):
        """R: manual public restart failure도 공용 build log helper를 사용한다."""
        mgr = _make_manager(tmp_path)
        _prepare_frontend_runtime_files(mgr.frontend_dir)
        (mgr.frontend_dir / "build").mkdir(parents=True, exist_ok=True)

        mock_result = MagicMock()
        mock_result.returncode = 15
        mock_result.stdout = "preview stdout"
        mock_result.stderr = "preview stderr"

        with patch("scripts.services.browser_worker_runtime.frontend_actions.PROJECT_ROOT", tmp_path), patch(
            "scripts.services.browser_worker_runtime.frontend_actions.subprocess.run", return_value=mock_result
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions.write_frontend_build_log",
            wraps=frontend_mode.write_frontend_build_log,
        ) as mock_write, patch(
            "scripts.services.browser_worker_runtime.frontend_actions.cprint"
        ):
            ok = mgr._run_frontend_build_if_needed(public=True, timestamp="20260424_102000")

        assert ok is True
        mock_write.assert_called_once()
        assert mock_write.call_args.args[0] == tmp_path / "logs"
        assert mock_write.call_args.kwargs["public"] is True
        build_logs = list((tmp_path / "logs").glob("frontend_build_public_*.log"))
        assert len(build_logs) == 1
        content = build_logs[0].read_text(encoding="utf-8")
        assert "preview stdout" in content
        assert "preview stderr" in content

    def test_restart_frontend_public_fallback_message_includes_build_log_boundary(self, tmp_path):
        """B: fallback preview 문구에 build log 경로가 포함된다."""
        mgr = _make_manager(tmp_path)
        _prepare_frontend_runtime_files(mgr.frontend_dir)
        (mgr.frontend_dir / "build").mkdir(parents=True, exist_ok=True)

        mock_result = MagicMock()
        mock_result.returncode = 15
        mock_result.stdout = ""
        mock_result.stderr = "build failed"

        with patch("scripts.services.browser_worker_runtime.frontend_actions.PROJECT_ROOT", tmp_path), patch(
            "scripts.services.browser_worker_runtime.frontend_actions.subprocess.run", return_value=mock_result
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions.cprint"
        ) as mock_cprint:
            ok = mgr._run_frontend_build_if_needed(public=True, timestamp="20260424_102100")

        assert ok is True
        build_logs = list((tmp_path / "logs").glob("frontend_build_public_*.log"))
        assert len(build_logs) == 1
        build_log = build_logs[0]
        rendered = [str(call.args[0]) for call in mock_cprint.call_args_list if call.args]
        assert f"Using previous build artifact for fallback preview (class=other, build_log={build_log})" in rendered

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
            "scripts.services.browser_worker_runtime.manager.tracked_popen_sync", return_value=mock_proc
        ), patch(
            "scripts.services.browser_worker_runtime.manager.pick_listener_pid", return_value=1234
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions._wait_for_frontend_listener", return_value=5678
        ), patch(
            "scripts.services.browser_worker_runtime.manager.time.sleep", return_value=None
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions._wait_for_frontend_http_ready",
            return_value=(True, None),
        ) as mock_urlopen:
            ok = mgr.restart_frontend(public=False)

        assert ok is False
        mock_urlopen.assert_not_called()

    def test_restart_frontend_boundary_does_not_write_launcher_pid_when_listener_missing(self, tmp_path):
        """B: listener 미감지 상태에서는 launcher PID를 frontend.pid에 기록하지 않는다."""
        mgr = _make_manager(tmp_path)
        mock_proc = MagicMock()
        mock_proc.pid = 5555

        with patch.object(mgr, "_acquire_frontend_restart_lock", return_value=104), patch.object(
            mgr, "_release_frontend_restart_lock"
        ), patch.object(mgr, "_cleanup_frontend_runtime"), patch.object(mgr, "_prepare_frontend_env"), patch.object(
            mgr, "_run_frontend_build_if_needed", return_value=True
        ), patch.object(
            mgr, "_has_port_collision_error", return_value=False
        ), patch(
            "scripts.services.browser_worker_runtime.manager.tracked_popen_sync", return_value=mock_proc
        ), patch(
            "scripts.services.browser_worker_runtime.manager.pick_listener_pid", return_value=1234
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions._wait_for_frontend_listener", return_value=None
        ), patch(
            "scripts.services.browser_worker_runtime.manager.is_process_alive", return_value=True
        ), patch(
            "scripts.services.browser_worker_runtime.manager.time.sleep", return_value=None
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions._wait_for_frontend_http_ready",
            return_value=(False, "connection refused"),
        ), patch(
            "scripts.services.browser_worker_runtime.manager.write_pid_file"
        ) as mock_write, patch(
            "scripts.services.browser_worker_runtime.manager.remove_pid_file"
        ) as mock_remove:
            ok = mgr.restart_frontend(public=False)

        assert ok is False
        mock_write.assert_not_called()
        mock_remove.assert_called()

    def test_restart_frontend_boundary_listener_pid_unchanged_but_healthy_succeeds(self, tmp_path):
        """B: listener PID가 유지돼도 HTTP health가 복구되면 성공으로 본다."""
        mgr = _make_manager(tmp_path)
        mock_proc = MagicMock()
        mock_proc.pid = 9090

        with patch.object(mgr, "_acquire_frontend_restart_lock", return_value=105), patch.object(
            mgr, "_release_frontend_restart_lock"
        ), patch.object(mgr, "_cleanup_frontend_runtime"), patch.object(mgr, "_prepare_frontend_env"), patch.object(
            mgr, "_run_frontend_build_if_needed", return_value=True
        ), patch.object(
            mgr, "_has_port_collision_error", return_value=False
        ), patch(
            "scripts.services.browser_worker_runtime.manager.tracked_popen_sync", return_value=mock_proc
        ), patch(
            "scripts.services.browser_worker_runtime.manager.pick_listener_pid", return_value=4444
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions._wait_for_frontend_listener", return_value=4444
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions._wait_for_frontend_http_ready",
            return_value=(True, None),
        ), patch(
            "scripts.services.browser_worker_runtime.manager.time.sleep", return_value=None
        ), patch(
            "scripts.services.browser_worker_runtime.manager.write_pid_file"
        ) as mock_write, patch(
            "scripts.services.browser_worker_runtime.frontend_actions.cprint"
        ) as mock_cprint:
            ok = mgr.restart_frontend(public=False)

        assert ok is True
        mock_write.assert_called_once()
        rendered = [str(call.args[0]) for call in mock_cprint.call_args_list if call.args]
        assert any("Listener PID unchanged after restart" in line and "frontend is healthy" in line for line in rendered)

    def test_restart_frontend_error_listener_pid_unchanged_and_unhealthy_fails(self, tmp_path):
        """E: listener PID가 유지되고 health도 복구되지 않으면 실패해야 한다."""
        mgr = _make_manager(tmp_path)
        mock_proc = MagicMock()
        mock_proc.pid = 9191

        with patch.object(mgr, "_acquire_frontend_restart_lock", return_value=106), patch.object(
            mgr, "_release_frontend_restart_lock"
        ), patch.object(mgr, "_cleanup_frontend_runtime"), patch.object(mgr, "_prepare_frontend_env"), patch.object(
            mgr, "_run_frontend_build_if_needed", return_value=True
        ), patch.object(
            mgr, "_has_port_collision_error", return_value=False
        ), patch(
            "scripts.services.browser_worker_runtime.manager.tracked_popen_sync", return_value=mock_proc
        ), patch(
            "scripts.services.browser_worker_runtime.manager.pick_listener_pid", return_value=5555
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions._wait_for_frontend_listener", return_value=5555
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions._wait_for_frontend_http_ready",
            return_value=(False, "connection refused"),
        ), patch(
            "scripts.services.browser_worker_runtime.manager.time.sleep", return_value=None
        ), patch(
            "scripts.services.browser_worker_runtime.manager.write_pid_file"
        ) as mock_write, patch(
            "scripts.services.browser_worker_runtime.frontend_actions._emit_listener_diagnostics"
        ) as mock_diag, patch(
            "scripts.services.browser_worker_runtime.frontend_actions.cprint"
        ) as mock_cprint:
            ok = mgr.restart_frontend(public=False)

        assert ok is False
        mock_write.assert_called_once()
        rendered = [str(call.args[0]) for call in mock_cprint.call_args_list if call.args]
        assert any(line == "Listener PID unchanged after restart (PID: 5555)" for line in rendered)
        mock_diag.assert_any_call(6101, "Listener PID remained unchanged and frontend health did not recover", frontend_actions.RED)
        mock_diag.assert_any_call(6101, "Frontend restart failed health gate", frontend_actions.RED)


class TestListenerPidAndStatus:
    def test_describe_listener_owner_error_returns_structured_field(self):
        """B: owner 조회 실패는 owner_error 구조 필드로 남긴다."""
        proc = MagicMock()
        proc.name.return_value = "node.exe"
        proc.username.side_effect = PermissionError("Access denied")
        proc.cmdline.return_value = ["npm.cmd", "run", "preview", "--", "--port", "6100"]
        proc.exe.return_value = r"C:\Program Files\nodejs\node.exe"

        with patch("service_utils.pick_listener_pid", return_value=5151), patch(
            "service_utils.psutil.Process", return_value=proc
        ):
            metadata = service_utils.describe_listener(6100)

        assert metadata["pid"] == 5151
        assert metadata["name"] == "node.exe"
        assert metadata["owner"] is None
        assert "PermissionError: Access denied" == metadata["owner_error"]
        assert "--port 6100" in str(metadata["cmdline"])
        assert str(metadata["exe"]).endswith("node.exe")

    def test_restart_frontend_error_access_denied_emits_listener_metadata(self, tmp_path):
        """E: listener 종료 실패 시 metadata와 권한 힌트를 함께 출력한다."""
        mgr = _make_manager(tmp_path)
        pid_file = mgr.pid_dir / "frontend_admin.pid"

        with patch(
            "scripts.services.browser_worker_runtime.manager.read_pid_file", return_value=4444
        ), patch(
            "scripts.services.browser_worker_runtime.manager.is_process_alive", return_value=True
        ), patch(
            "scripts.services.browser_worker_runtime.manager.find_pids_on_port", return_value=[]
        ), patch(
            "scripts.services.browser_worker_runtime.manager.kill_pid", return_value=False
        ), patch(
            "scripts.services.browser_worker_runtime.manager.remove_pid_file"
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions.describe_listener",
            return_value={
                "port": 6101,
                "pid": 4444,
                "name": "node.exe",
                "owner": None,
                "owner_error": "PermissionError: Access denied",
                "cmdline": "npm.cmd run dev -- --host --port 6101",
                "exe": r"C:\Program Files\nodejs\node.exe",
            },
        ), patch(
            "scripts.services.browser_worker_runtime.frontend_actions.cprint"
        ) as mock_cprint:
            terminated = frontend_actions._cleanup_frontend_runtime(mgr, mgr.frontend_port, pid_file)

        assert terminated == []
        rendered = [str(call.args[0]) for call in mock_cprint.call_args_list if call.args]
        assert any("Failed to terminate PID 4444 while clearing port 6101" in line for line in rendered)
        assert any("owner_error=PermissionError: Access denied" in line for line in rendered)
        assert any("Listener cleanup may require elevation or another session owns the port" in line for line in rendered)

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
            "scripts.services.browser_worker_runtime.manager.read_pid_file", return_value=None
        ), patch(
            "scripts.services.browser_worker_runtime.manager.is_port_listening", side_effect=[True, False]
        ), patch(
            "scripts.services.browser_worker_runtime.manager.pick_listener_pid", return_value=7777
        ), patch(
            "scripts.services.browser_worker_runtime.manager.write_pid_file"
        ) as mock_write:
            mgr.status()

        mock_write.assert_called_once_with(admin_pid_file, 7777)

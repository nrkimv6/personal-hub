import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.services import service_run
from scripts.services.service_run import ServiceRunner


def _make_runner(tmp_path: Path) -> ServiceRunner:
    runner = object.__new__(ServiceRunner)
    runner.dev = False
    runner.api_port = 8000
    runner.frontend_port = 6100
    runner.app_mode = "public"
    runner.pid_suffix = ""
    runner.log_dir = tmp_path / "logs"
    runner.pid_dir = tmp_path / ".pids"
    runner.log_dir.mkdir(parents=True, exist_ok=True)
    runner.pid_dir.mkdir(parents=True, exist_ok=True)
    runner.log = MagicMock()
    runner._frontend_proc = None
    runner._frontend_monitor_thread = None
    runner._frontend_monitor_stop = threading.Event()
    runner._frontend_restart_lock = threading.Lock()
    runner._frontend_state_lock = threading.Lock()
    runner._frontend_health = "unknown"
    runner._frontend_degraded_reason = None
    runner._frontend_last_build_error_at = None
    runner._frontend_listener_pid = None
    runner._frontend_retry_count = 0
    runner._cleaned_up = False
    return runner


def _prepare_frontend_workspace(tmp_path: Path) -> Path:
    frontend_dir = tmp_path / "frontend"
    (frontend_dir / "node_modules" / ".bin").mkdir(parents=True, exist_ok=True)
    (frontend_dir / "node_modules" / ".bin" / "vite.cmd").write_text("@echo off\n", encoding="utf-8")
    return frontend_dir


class _FakeProc:
    def __init__(self, pid: int):
        self.pid = pid

    def poll(self):
        return None


def test_service_run_public_build_failure_without_artifact_marks_api_only(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    frontend_dir = _prepare_frontend_workspace(tmp_path)
    monkeypatch.setattr(service_run, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "build failed"
    mock_result.stdout = ""

    with patch.object(service_run, "find_pids_on_port", return_value=[]), patch.object(
        service_run, "is_process_alive", return_value=False
    ), patch.object(service_run, "kill_pid"), patch.object(service_run, "read_pid_file", return_value=None), patch.object(
        service_run, "remove_pid_file"
    ), patch.object(
        service_run, "pick_listener_pid", return_value=None
    ), patch.object(
        service_run.subprocess, "run", return_value=mock_result
    ), patch.object(
        service_run.subprocess, "Popen"
    ) as mock_popen:
        proc = runner.start_frontend()

    assert proc is None
    mock_popen.assert_not_called()
    assert runner._frontend_health == "down"
    assert runner._frontend_degraded_reason == "build_failed"
    assert not (runner.pid_dir / "frontend.pid").exists()


def test_service_run_public_build_failure_with_artifact_fallback_records_listener_pid(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    frontend_dir = _prepare_frontend_workspace(tmp_path)
    (frontend_dir / "build").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(service_run, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "build failed"
    mock_result.stdout = ""

    mock_proc = _FakeProc(4321)

    with patch.object(service_run, "find_pids_on_port", return_value=[]), patch.object(
        service_run, "is_process_alive", return_value=False
    ), patch.object(service_run, "kill_pid"), patch.object(service_run, "read_pid_file", return_value=None), patch.object(
        service_run, "remove_pid_file"
    ), patch.object(
        service_run, "pick_listener_pid", side_effect=[None, 5555]
    ), patch.object(
        service_run.subprocess, "run", return_value=mock_result
    ), patch.object(
        service_run.subprocess, "Popen", return_value=mock_proc
    ), patch.object(
        service_run.time, "sleep", return_value=None
    ):
        proc = runner.start_frontend()

    assert proc is mock_proc
    assert runner._frontend_health == "degraded"
    assert runner._frontend_degraded_reason == "build_failed_with_fallback"
    assert runner._frontend_listener_pid == 5555
    assert (runner.pid_dir / "frontend.pid").read_text(encoding="ascii") == "5555"

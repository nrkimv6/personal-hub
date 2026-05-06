from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch

from scripts.services import service_run
from scripts.services import frontend_mode


def _info_lines(log: MagicMock) -> list[str]:
    return [str(call.args[0]) for call in log.info.call_args_list if call.args]


def _prepare_frontend_workspace(frontend_dir: Path, *, with_build: bool) -> None:
    vite_bin = frontend_dir / "node_modules" / ".bin" / "vite.cmd"
    vite_bin.parent.mkdir(parents=True, exist_ok=True)
    vite_bin.write_text("@echo off\r\n", encoding="utf-8")

    base_tsconfig = frontend_dir / ".svelte-kit" / "tsconfig.json"
    base_tsconfig.parent.mkdir(parents=True, exist_ok=True)
    base_tsconfig.write_text("{\"compilerOptions\":{}}", encoding="utf-8")

    if with_build:
        (frontend_dir / "build").mkdir(parents=True, exist_ok=True)


def test_service_runner_log_environment_reports_boot_paths():
    logger = MagicMock()
    fingerprint = {
        "runtime_fingerprint": "runtime-fp-1234567890",
        "source_fingerprint": "source-fp-1234567890",
        "source_files": [{"path": "app/main.py", "present": True}],
    }

    with patch.object(service_run, "setup_service_logger", return_value=logger), patch.object(
        service_run, "get_session_id", return_value=7
    ), patch.object(service_run, "get_runtime_fingerprint_snapshot", return_value=fingerprint), patch(
        "socket.getaddrinfo", return_value=[("localhost", None, None, None, None)]
    ):
        runner = service_run.ServiceRunner(dev=True)
        runner.log_environment()

    lines = _info_lines(logger)
    assert any("Script:" in line and str(Path(service_run.__file__).resolve()) in line for line in lines)
    assert any("PROJECT_ROOT:" in line and str(service_run.PROJECT_ROOT) in line for line in lines)
    assert any("sys.path[0]:" in line and str(service_run.PROJECT_ROOT) in line for line in lines)
    assert any("Runtime fingerprint:" in line and "source=" in line and "files=1" in line for line in lines)
    assert any("CWD:" in line for line in lines)


def test_service_run_project_root_resolves_to_repo_root():
    expected_root = Path(__file__).resolve().parents[1]
    assert service_run.PROJECT_ROOT == expected_root


def test_service_run_import_does_not_pull_app_core_config_subprocess():
    script = """
import sys
before = set(sys.modules)
from scripts.services import service_run
after = set(sys.modules) - before
print("app.core.config" in after)
print(service_run.PROJECT_ROOT)
"""
    env = dict(service_run.os.environ)
    env.pop("APP_MODE", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=True,
    )

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert lines[0] == "False"
    assert Path(lines[1]) == Path(__file__).resolve().parents[1]


def test_runtime_mode_prefers_env_over_stale_settings_subprocess():
    script = """
import os
from app.core.config import settings, get_runtime_app_mode
print(settings.APP_MODE)
os.environ["APP_MODE"] = "admin"
print(get_runtime_app_mode(settings_app_mode=settings.APP_MODE))
"""
    env = dict(service_run.os.environ)
    env.pop("APP_MODE", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=True,
    )

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip() in {"public", "admin"}]
    assert lines[-2:] == ["public", "admin"]


def test_service_runner_frontend_runtime_env_separates_admin_and_public_modes():
    runner = object.__new__(service_run.ServiceRunner)
    runner.api_port = 8001

    admin_env = runner._frontend_runtime_env(public=False)
    assert admin_env["MONITOR_FRONTEND_MODE"] == "admin"
    assert admin_env["MONITOR_SVELTEKIT_OUTDIR"] == ".svelte-kit-admin"
    assert admin_env["VITE_API_PORT"] == "8001"

    public_env = runner._frontend_runtime_env(public=True)
    assert public_env["MONITOR_FRONTEND_MODE"] == "public"
    assert public_env["MONITOR_SVELTEKIT_OUTDIR"] == ".svelte-kit-public"
    assert "VITE_API_PORT" not in public_env


def test_public_service_runner_cleanup_uses_public_pid_files_only(tmp_path):
    runner = service_run.ServiceRunner(dev=False)
    runner.pid_dir = tmp_path / ".pids"
    runner.pid_dir.mkdir()
    for name in ["api.pid", "frontend.pid", "api_admin.pid", "frontend_admin.pid"]:
        (runner.pid_dir / name).write_text("1234", encoding="utf-8")

    removed: list[str] = []

    with patch("scripts.services.service_run.read_pid_file", return_value=1234), patch(
        "scripts.services.service_run.is_process_alive", return_value=False
    ), patch("scripts.services.service_run.remove_pid_file", side_effect=lambda path: removed.append(path.name)):
        runner._cleanup_stale_pids()

    assert removed == ["api.pid", "frontend.pid"]


def test_ensure_frontend_runtime_tsconfigs_copies_base_config_for_both_modes(tmp_path):
    frontend_dir = tmp_path / "frontend"
    base_dir = frontend_dir / ".svelte-kit"
    base_dir.mkdir(parents=True)
    base_tsconfig = base_dir / "tsconfig.json"
    base_tsconfig.write_text("{\"compilerOptions\":{}}", encoding="utf-8")

    frontend_mode.ensure_frontend_runtime_tsconfigs(frontend_dir)

    admin_tsconfig = frontend_dir / ".svelte-kit-admin" / "tsconfig.json"
    public_tsconfig = frontend_dir / ".svelte-kit-public" / "tsconfig.json"
    assert admin_tsconfig.read_text(encoding="utf-8") == base_tsconfig.read_text(encoding="utf-8")
    assert public_tsconfig.read_text(encoding="utf-8") == base_tsconfig.read_text(encoding="utf-8")


def test_public_build_failure_writes_frontend_build_log_right(tmp_path):
    frontend_dir = tmp_path / "frontend"
    _prepare_frontend_workspace(frontend_dir, with_build=True)
    logger = MagicMock()
    build_result = MagicMock(returncode=15, stdout="vite stdout", stderr="vite stderr")
    preview_proc = MagicMock(pid=2468)

    with patch.object(service_run, "PROJECT_ROOT", tmp_path), patch.object(
        service_run, "setup_service_logger", return_value=logger
    ), patch(
        "scripts.services.service_run.subprocess.run", return_value=build_result
    ) as mock_run, patch(
        "scripts.services.service_run.subprocess.Popen", return_value=preview_proc
    ), patch(
        "scripts.services.service_run.write_pid_file"
    ):
        runner = service_run.ServiceRunner(dev=False)
        proc = runner.start_frontend()

    assert proc is preview_proc
    build_logs = list((tmp_path / "logs").glob("frontend_build_public_*.log"))
    assert len(build_logs) == 1
    build_log = build_logs[0]
    content = build_log.read_text(encoding="utf-8")
    assert "mode=public" in content
    assert "outDir=.svelte-kit-public" in content
    assert "vite stdout" in content
    assert "vite stderr" in content
    error_messages = [str(call.args[0]) for call in logger.error.call_args_list if call.args]
    warning_messages = [str(call.args[0]) for call in logger.warning.call_args_list if call.args]
    assert any("Frontend build failed (rc=%s, class=%s, log=%s, listener=%s)" in msg for msg in error_messages)
    assert any("Using previous build for preview (class=other, build_log=" in msg for msg in warning_messages)
    assert mock_run.call_args.kwargs["env"]["MONITOR_FRONTEND_MODE"] == "public"


def test_public_build_failure_empty_streams_boundary(tmp_path):
    frontend_dir = tmp_path / "frontend"
    _prepare_frontend_workspace(frontend_dir, with_build=False)
    logger = MagicMock()
    build_result = MagicMock(returncode=15, stdout="", stderr="")

    with patch.object(service_run, "PROJECT_ROOT", tmp_path), patch.object(
        service_run, "setup_service_logger", return_value=logger
    ), patch(
        "scripts.services.service_run.subprocess.run", return_value=build_result
    ), patch(
        "scripts.services.service_run.subprocess.Popen"
    ) as mock_popen:
        runner = service_run.ServiceRunner(dev=False)
        proc = runner.start_frontend()

    assert proc is None
    mock_popen.assert_not_called()
    build_logs = list((tmp_path / "logs").glob("frontend_build_public_*.log"))
    assert len(build_logs) == 1
    build_log = build_logs[0]
    content = build_log.read_text(encoding="utf-8")
    assert "[stdout]\n(no output)" in content
    assert "[stderr]\n(no output)" in content
    assert any(
        "No previous build found - Frontend unavailable, API-only mode (class=other, build_log="
        for call in logger.warning.call_args_list
        if call.args
    )


def test_public_build_failure_logs_permission_classification_right(tmp_path):
    frontend_dir = tmp_path / "frontend"
    _prepare_frontend_workspace(frontend_dir, with_build=True)
    logger = MagicMock()
    build_result = MagicMock(returncode=1, stdout="", stderr="EPERM: Access denied")
    preview_proc = MagicMock(pid=1357)

    with patch.object(service_run, "PROJECT_ROOT", tmp_path), patch.object(
        service_run, "setup_service_logger", return_value=logger
    ), patch(
        "scripts.services.service_run.subprocess.run", return_value=build_result
    ), patch(
        "scripts.services.service_run.subprocess.Popen", return_value=preview_proc
    ), patch(
        "scripts.services.service_run.write_pid_file"
    ):
        runner = service_run.ServiceRunner(dev=False)
        proc = runner.start_frontend()

    assert proc is preview_proc
    assert any("class=build_lock_permission" in str(call.args[0]) for call in logger.warning.call_args_list if call.args)
    assert any("Build lock/permission detected" in str(call.args[0]) for call in logger.warning.call_args_list if call.args)


def test_public_build_failure_stdout_only_integration(tmp_path):
    build_log = frontend_mode.write_frontend_build_log(
        tmp_path / "logs",
        "20260424_101500",
        public=True,
        returncode=15,
        stdout="stdout only",
        stderr="",
    )

    assert build_log.name == "frontend_build_public_20260424_101500.log"
    content = build_log.read_text(encoding="utf-8")
    assert "[stdout]\nstdout only" in content
    assert "[stderr]\n(no output)" in content


def test_public_build_failure_stderr_only_integration(tmp_path):
    build_log = frontend_mode.write_frontend_build_log(
        tmp_path / "logs",
        "20260424_101501",
        public=True,
        returncode=15,
        stdout="",
        stderr="stderr only",
    )

    content = build_log.read_text(encoding="utf-8")
    assert "[stdout]\n(no output)" in content
    assert "[stderr]\nstderr only" in content

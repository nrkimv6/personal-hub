from __future__ import annotations

import builtins
from pathlib import Path
import json
import subprocess
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

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


def _service_runner_for_preflight() -> service_run.ServiceRunner:
    runner = object.__new__(service_run.ServiceRunner)
    runner.log = MagicMock()
    runner._preflighted_api_app = None
    return runner


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
    assert any("Entry script:" in line for line in lines)
    assert any("Runner module:" in line and str(Path(service_run.__file__).resolve()) in line for line in lines)
    assert any("PROJECT_ROOT:" in line and str(service_run.PROJECT_ROOT) in line for line in lines)
    assert any("sys.path[0]:" in line and str(service_run.PROJECT_ROOT) in line for line in lines)
    assert any("Runtime fingerprint:" in line and "source=" in line and "files=1" in line for line in lines)
    assert any("CWD:" in line for line in lines)
    assert any("scripts/services/__pycache__/service_run.cpython-" in line for line in lines)


def test_service_runner_main_accepts_admin_and_public_modes_R(capsys):
    assert service_run.main(["--admin", "--dry-run-bootstrap"]) == 0
    admin = json.loads(capsys.readouterr().out)
    assert admin["app_mode"] == "admin"
    assert service_run.os.environ["APP_MODE"] == "admin"
    assert service_run.os.environ["PYTHONIOENCODING"] == "utf-8"

    assert service_run.main(["--dry-run-bootstrap"]) == 0
    public = json.loads(capsys.readouterr().out)
    assert public["app_mode"] == "public"
    assert service_run.os.environ["APP_MODE"] == "public"
    assert public["runner_module"] == str(Path(service_run.__file__).resolve())


def test_service_install_uses_stable_stub_path_Co():
    source = (service_run.PROJECT_ROOT / "scripts" / "services" / "service-install.ps1").read_text(encoding="utf-8")
    assert '$ServiceScript = Join-Path $ProjectRoot "scripts\\service_run.py"' in source
    assert '$ServiceScript = Join-Path $ScriptDir "service_run.py"' not in source
    assert "Direct runner AppParameters detected" in source


def test_service_run_filesystem_entrypoints_share_bootstrap_contract_T3():
    root = Path(__file__).resolve().parents[1]
    env = dict(service_run.os.environ)
    env.pop("APP_MODE", None)
    env.pop("MONITOR_SERVICE_RUN_ENTRY_SCRIPT", None)

    stub_result = subprocess.run(
        [sys.executable, str(root / "scripts" / "service_run.py"), "--admin", "--dry-run-bootstrap"],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=True,
    )
    direct_result = subprocess.run(
        [sys.executable, str(root / "scripts" / "services" / "service_run.py"), "--admin", "--dry-run-bootstrap"],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=True,
    )

    stub = json.loads(stub_result.stdout)
    direct = json.loads(direct_result.stdout)
    assert stub["app_mode"] == direct["app_mode"] == "admin"
    assert stub["project_root"] == direct["project_root"] == str(root)
    assert stub["runner_module"] == direct["runner_module"] == str(root / "scripts" / "services" / "service_run.py")
    assert stub["entry_script"] == str(root / "scripts" / "service_run.py")
    assert direct["entry_script"] == str(root / "scripts" / "services" / "service_run.py")


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


@pytest.mark.parametrize("missing_name", ["missing_dependency_a", "missing_dependency_b"])
def test_service_runner_preflight_any_import_error_stops_before_frontend_E(missing_name):
    runner = _service_runner_for_preflight()
    error = ModuleNotFoundError(f"No module named '{missing_name}'", name=missing_name)

    with patch("scripts.services.service_run.importlib.import_module", side_effect=error) as mock_import:
        with pytest.raises(RuntimeError, match="API startup import preflight failed before frontend start"):
            runner._preflight_api_import_contract()

    mock_import.assert_called_once_with("app.main")
    runner.log.error.assert_called_once()
    error_call = runner.log.error.call_args
    assert "API startup import preflight failed before frontend start" in str(error_call.args[0])
    assert "ModuleNotFoundError" in error_call.args
    assert missing_name in error_call.args
    assert error_call.kwargs["exc_info"] is True
    assert error_call.kwargs["extra"]["api_preflight_import_name"] == missing_name
    assert runner._preflighted_api_app is None


@pytest.mark.parametrize(
    ("exception", "expected_type"),
    [
        (ImportError("cannot import app.main dependency", name="app.main"), "ImportError"),
        (RuntimeError("startup hook exploded"), "RuntimeError"),
    ],
)
def test_service_runner_preflight_app_main_import_exception_is_structured_E(exception, expected_type):
    runner = _service_runner_for_preflight()

    with patch("scripts.services.service_run.importlib.import_module", side_effect=exception):
        with pytest.raises(RuntimeError, match=expected_type):
            runner._preflight_api_import_contract()

    error_call = runner.log.error.call_args
    assert "API startup import preflight failed before frontend start" in str(error_call.args[0])
    assert expected_type in error_call.args
    assert error_call.kwargs["extra"]["api_preflight_exception_type"] == expected_type
    assert error_call.kwargs["extra"]["api_preflight_exception_message"] == str(exception)


def test_service_runner_preflight_imports_main_before_frontend_O():
    runner = _service_runner_for_preflight()
    app = object()
    module = types.SimpleNamespace(app=app)

    with patch("scripts.services.service_run.importlib.import_module", return_value=module) as mock_import:
        result = runner._preflight_api_import_contract()

    assert result is app
    assert runner._preflighted_api_app is app
    mock_import.assert_called_once_with("app.main")
    assert any(
        "API startup import preflight passed before frontend start" in str(call.args[0])
        for call in runner.log.info.call_args_list
    )


def test_service_runner_preflight_failure_does_not_start_frontend_T3(tmp_path):
    runner = _service_runner_for_preflight()
    runner.dev = True
    runner.app_mode = "admin"
    runner.api_port = 8001
    runner.frontend_port = 6101
    runner.pid_dir = tmp_path
    runner._preflight_api_import_contract = MagicMock(side_effect=RuntimeError("missing dependency"))
    runner.cleanup_before_start = MagicMock()
    runner.start_frontend = MagicMock()
    runner.run_api = MagicMock()
    runner.cleanup = MagicMock()

    with patch("scripts.services.service_run.bootstrap_service_environment"), patch("atexit.register"), patch(
        "signal.signal"
    ), patch("sys.exit", side_effect=SystemExit) as mock_exit:
        with pytest.raises(SystemExit):
            runner.run()

    runner.cleanup_before_start.assert_called_once()
    runner._preflight_api_import_contract.assert_called_once()
    runner.start_frontend.assert_not_called()
    runner.run_api.assert_not_called()
    runner.cleanup.assert_called_once()
    assert not (tmp_path / "frontend_admin.pid").exists()
    mock_exit.assert_called_once_with(1)


def test_service_runner_preflight_success_preserves_frontend_then_api_order_T3():
    runner = _service_runner_for_preflight()
    runner.dev = True
    runner.app_mode = "admin"
    runner.api_port = 8001
    runner.frontend_port = 6101
    events: list[str] = []
    app = object()
    frontend_proc = object()

    def preflight():
        events.append("preflight")
        runner._preflighted_api_app = app
        return app

    def start_frontend():
        events.append("start_frontend")
        return frontend_proc

    def run_api():
        assert runner._preflighted_api_app is app
        events.append("run_api")

    runner.cleanup_before_start = MagicMock(side_effect=lambda: events.append("cleanup_before_start"))
    runner._preflight_api_import_contract = MagicMock(side_effect=preflight)
    runner.start_frontend = MagicMock(side_effect=start_frontend)
    runner.run_api = MagicMock(side_effect=run_api)
    runner.cleanup = MagicMock(side_effect=lambda: events.append("cleanup"))

    with patch("scripts.services.service_run.bootstrap_service_environment"), patch("atexit.register"), patch(
        "signal.signal"
    ), patch("sys.exit", side_effect=SystemExit) as mock_exit:
        with pytest.raises(SystemExit):
            runner.run()

    assert runner._frontend_proc is frontend_proc
    assert events == ["cleanup_before_start", "preflight", "start_frontend", "run_api", "cleanup"]
    mock_exit.assert_called_once_with(0)


def test_service_runner_run_api_reuses_preflighted_app_without_reimport_T3(monkeypatch, tmp_path):
    runner = _service_runner_for_preflight()
    runner.dev = True
    runner.api_port = 8001
    runner.pid_suffix = "_admin"
    runner.pid_dir = tmp_path
    app = object()
    runner._preflighted_api_app = app
    runner.check_crash_loop = MagicMock(return_value=False)
    captured: dict[str, object] = {}

    config_module = types.ModuleType("app.config")
    config_module.settings = types.SimpleNamespace(APP_MODE="admin")
    server_state_module = types.ModuleType("app.core.server_state")
    server_state_module.set_server = lambda server: captured.setdefault("server", server)
    death_log_module = types.ModuleType("app.core.death_log")
    death_log_module.read_recent_deaths = lambda window_minutes=1, exclude_causes=None: []
    death_log_module.record_death = lambda **kwargs: captured.setdefault("death", kwargs)

    class FakeConfig:
        def __init__(self, config_app, **kwargs):
            captured["config_app"] = config_app
            captured["config_kwargs"] = kwargs

    class FakeServer:
        exit_code = 0

        def __init__(self, config):
            self.config = config
            self.should_exit = True

        def run(self):
            captured["server_run"] = True

    uvicorn_module = types.ModuleType("uvicorn")
    uvicorn_module.Config = FakeConfig
    uvicorn_module.Server = FakeServer

    monkeypatch.setitem(sys.modules, "app.config", config_module)
    monkeypatch.setitem(sys.modules, "app.core.server_state", server_state_module)
    monkeypatch.setitem(sys.modules, "app.core.death_log", death_log_module)
    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn_module)

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "app.main":
            raise AssertionError("run_api re-imported app.main after preflight")
        return original_import(name, *args, **kwargs)

    with patch("scripts.services.service_run._log_mode_alignment", return_value=True), patch(
        "scripts.services.service_run.write_pid_file"
    ), patch("builtins.__import__", side_effect=guarded_import):
        runner.run_api()

    assert captured["config_app"] is app
    assert captured["server_run"] is True


def test_service_runner_install_hooks_idempotent_under_repeat_import_O(monkeypatch):
    runner = _service_runner_for_preflight()
    app = object()
    counters = {"install_hooks": 0, "init_extra_tables": 0}
    monkeypatch.delitem(sys.modules, "app.main", raising=False)

    def fake_import_module(name: str):
        assert name == "app.main"
        cached = sys.modules.get("app.main")
        if cached is not None:
            return cached
        counters["install_hooks"] += 1
        counters["init_extra_tables"] += 1
        module = types.ModuleType("app.main")
        module.app = app
        monkeypatch.setitem(sys.modules, "app.main", module)
        return module

    with patch("scripts.services.service_run.importlib.import_module", side_effect=fake_import_module):
        assert runner._preflight_api_import_contract() is app
        assert runner._preflight_api_import_contract() is app

    assert counters == {"install_hooks": 1, "init_extra_tables": 1}


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

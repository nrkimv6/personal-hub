from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.services import service_run
from scripts.services import frontend_mode


def _info_lines(log: MagicMock) -> list[str]:
    return [str(call.args[0]) for call in log.info.call_args_list if call.args]


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

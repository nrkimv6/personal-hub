from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from tests.helpers.subprocess_utils import run_proc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WATCHDOG_UTILS = PROJECT_ROOT / "scripts" / "watchdogs" / "watchdog-utils.ps1"

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="PowerShell watchdogs are Windows-only")


def _run_ps_fixture(tmp_path: Path, body: str, *, app_mode: str = "public", timeout: float = 15):
    script_path = tmp_path / "watchdog_utils_probe.ps1"
    script_path.write_text(
        "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                f". '{WATCHDOG_UTILS}'",
                body,
            ]
        ),
        encoding="utf-8",
    )
    env = {**os.environ, "APP_MODE": app_mode}
    result = run_proc(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
        cwd=str(PROJECT_ROOT),
        timeout=timeout,
        env=env,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_get_watchdog_paths_r_admin_mode(tmp_path: Path):
    probe_root = tmp_path / "probe"
    payload = _run_ps_fixture(
        tmp_path,
        (
            f"$result = Get-WatchdogPaths -ProjectRoot '{probe_root}'\n"
            "$result | ConvertTo-Json -Compress"
        ),
        app_mode="admin",
    )
    assert payload["IsAdmin"] is True
    assert payload["PidSuffix"] == "_admin"
    assert Path(payload["LogDir"]) == probe_root / "logs" / "admin"
    assert Path(payload["PidDir"]) == probe_root / ".pids"
    assert (probe_root / "logs" / "admin").is_dir()
    assert (probe_root / ".pids").is_dir()


def test_get_watchdog_paths_r_public_mode(tmp_path: Path):
    probe_root = tmp_path / "probe"
    payload = _run_ps_fixture(
        tmp_path,
        (
            f"$result = Get-WatchdogPaths -ProjectRoot '{probe_root}'\n"
            "$result | ConvertTo-Json -Compress"
        ),
        app_mode="public",
    )
    assert payload["IsAdmin"] is False
    assert payload["PidSuffix"] == ""
    assert Path(payload["LogDir"]) == probe_root / "logs"
    assert Path(payload["PidDir"]) == probe_root / ".pids"


def test_test_pid_file_alive_r_alive(tmp_path: Path):
    pid_file = tmp_path / "alive.pid"
    payload = _run_ps_fixture(
        tmp_path,
        (
            f"$pidFile = '{pid_file}'\n"
            "$PID | Out-File $pidFile -Encoding ascii\n"
            "@{ alive = (Test-PidFileAlive -PidFile $pidFile) } | ConvertTo-Json -Compress"
        ),
    )
    assert payload["alive"] is True


def test_test_pid_file_alive_e_missing_file(tmp_path: Path):
    pid_file = tmp_path / "missing.pid"
    payload = _run_ps_fixture(
        tmp_path,
        (
            f"$pidFile = '{pid_file}'\n"
            "@{ alive = (Test-PidFileAlive -PidFile $pidFile) } | ConvertTo-Json -Compress"
        ),
    )
    assert payload["alive"] is False


def test_test_pid_file_alive_e_dead_pid(tmp_path: Path):
    pid_file = tmp_path / "dead.pid"
    payload = _run_ps_fixture(
        tmp_path,
        (
            f"$pidFile = '{pid_file}'\n"
            "'99999999' | Out-File $pidFile -Encoding ascii\n"
            "@{ alive = (Test-PidFileAlive -PidFile $pidFile) } | ConvertTo-Json -Compress"
        ),
    )
    assert payload["alive"] is False

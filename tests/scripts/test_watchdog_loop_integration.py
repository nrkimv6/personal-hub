from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.helpers.subprocess_utils import run_proc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WATCHDOG_UTILS = PROJECT_ROOT / "scripts" / "watchdogs" / "watchdog-utils.ps1"

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="PowerShell watchdogs are Windows-only")


def _run_loop_probe(tmp_path: Path, body: str, *, timeout: float = 20):
    script_path = tmp_path / "watchdog_loop_probe.ps1"
    script_path.write_text(
        "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                f"$script:watchdogLogFile = '{tmp_path / 'watchdog.log'}'",
                f". '{WATCHDOG_UTILS}'",
                body,
            ]
        ),
        encoding="utf-8",
    )
    result = run_proc(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
        cwd=str(PROJECT_ROOT),
        timeout=timeout,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_invoke_watchdog_loop_r_starts_and_keeps_alive(tmp_path: Path):
    payload = _run_loop_probe(
        tmp_path,
        """
$script:startCalls = 0
$script:testCalls = 0
$startTarget = { $script:startCalls++ }
$testRunning = {
    $script:testCalls++
    if ($script:testCalls -ge 4) {
        throw 'sentinel-end'
    }
    return $true
}
Invoke-WatchdogLoop -Label 'probe' -StartTarget $startTarget -TestRunning $testRunning -CheckInterval 0 -MaxRestarts 5 -RestartWindow 300
@{
    startCalls = $script:startCalls
    testCalls = $script:testCalls
    log = ([System.IO.File]::ReadAllText($script:watchdogLogFile))
} | ConvertTo-Json -Compress
""",
    )
    assert payload["startCalls"] == 0
    assert payload["testCalls"] == 4
    assert "Maximum restart limit" not in payload["log"]
    assert "Watchdog error: sentinel-end" in payload["log"]


def test_invoke_watchdog_loop_e_max_restart_breaks(tmp_path: Path):
    payload = _run_loop_probe(
        tmp_path,
        """
$script:startCalls = 0
$startTarget = { $script:startCalls++ }
$testRunning = { return $false }
Invoke-WatchdogLoop -Label 'probe' -StartTarget $startTarget -TestRunning $testRunning -CheckInterval 0 -MaxRestarts 5 -RestartWindow 300
@{
    startCalls = $script:startCalls
    log = ([System.IO.File]::ReadAllText($script:watchdogLogFile))
} | ConvertTo-Json -Compress
""",
    )
    assert payload["startCalls"] == 5
    assert "Maximum restart limit (5) reached" in payload["log"]
    assert "Watchdog stopped" in payload["log"]


def test_invoke_watchdog_loop_r_window_reset(tmp_path: Path):
    payload = _run_loop_probe(
        tmp_path,
        """
$script:startCalls = 0
$script:testCalls = 0
$startTarget = { $script:startCalls++ }
$testRunning = {
    $script:testCalls++
    switch ($script:testCalls) {
        1 { return $false }
        2 { return $false }
        default { throw 'window-reset-done' }
    }
}
Invoke-WatchdogLoop -Label 'probe' -StartTarget $startTarget -TestRunning $testRunning -CheckInterval 2 -MaxRestarts 5 -RestartWindow 1
@{
    startCalls = $script:startCalls
    testCalls = $script:testCalls
    log = ([System.IO.File]::ReadAllText($script:watchdogLogFile))
} | ConvertTo-Json -Compress
""",
        timeout=25,
    )
    assert payload["startCalls"] == 2
    assert payload["testCalls"] == 3
    assert "Restart count reset (no crashes in 1s)" in payload["log"]

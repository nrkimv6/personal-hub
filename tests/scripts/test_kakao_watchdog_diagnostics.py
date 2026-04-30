"""Kakao watchdog diagnostics contract tests."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WATCHDOG_PS1 = PROJECT_ROOT / "scripts" / "watchdogs" / "kakao-notification-watchdog.ps1"
MANAGER_PY = PROJECT_ROOT / "scripts" / "services" / "browser_worker_runtime" / "manager.py"
SETUP_ALIASES_PS1 = PROJECT_ROOT / "scripts" / "setup" / "setup-exe-aliases.ps1"


def test_kakao_watchdog_R_writes_self_pid_contract():
    source = WATCHDOG_PS1.read_text(encoding="utf-8")

    assert "$WatchdogPidFile = Join-Path $PidDir \"kakao_notification_watchdog_admin_self.pid\"" in source
    assert "$PID | Out-File $WatchdogPidFile -Encoding ascii" in source


def test_kakao_watchdog_R_creates_sentinel_flag_contract():
    source = WATCHDOG_PS1.read_text(encoding="utf-8")

    assert "$SentinelFile = Join-Path $LogDir \"kakao_watchdog_alive_$($PID).flag\"" in source
    assert "New-Item -ItemType File -Path $SentinelFile -Force" in source
    assert "(Get-Item $SentinelFile).LastWriteTime = Get-Date" in source


def test_kakao_watchdog_E_finally_cleans_up_contract():
    source = WATCHDOG_PS1.read_text(encoding="utf-8")

    assert "Remove-Item -LiteralPath $WatchdogPidFile -ErrorAction SilentlyContinue" in source
    assert "Remove-Item -LiteralPath $SentinelFile -ErrorAction SilentlyContinue" in source
    assert "Watchdog error position:" in source
    assert "$_.InvocationInfo.PositionMessage" in source
    assert "Watchdog stopped" in source


def test_manager_uses_kakao_powershell_alias():
    source = MANAGER_PY.read_text(encoding="utf-8")

    assert '_ps_alias("monitorpage-wdog-kakao.exe")' in source
    assert '"cmd": ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File",\n                        str(self.watchdogs_dir / "kakao-notification-watchdog.ps1")]' not in source


def test_setup_aliases_contains_kakao_watchdog_alias():
    source = SETUP_ALIASES_PS1.read_text(encoding="utf-8")

    assert '"monitorpage-wdog-kakao"    = "Kakao Notification Watchdog"' in source


def test_residual_sentinel_R_appends_anomaly_log(tmp_path):
    from scripts.services.browser_worker_runtime.watchdog_actions import _detect_kakao_residual_sentinel

    log_dir = tmp_path / "logs" / "admin"
    log_dir.mkdir(parents=True)
    sentinel = log_dir / "kakao_watchdog_alive_123.flag"
    sentinel.write_text("alive", encoding="utf-8")

    residuals = _detect_kakao_residual_sentinel(log_dir)

    assert residuals == [sentinel]
    assert not sentinel.exists()
    anomaly_log = tmp_path / "logs" / "kakao_watchdog_anomaly.log"
    assert anomaly_log.exists()
    content = anomaly_log.read_text(encoding="utf-8")
    assert "kakao_watchdog_alive_123.flag" in content


def test_residual_sentinel_B_no_residual_returns_empty(tmp_path):
    from scripts.services.browser_worker_runtime.watchdog_actions import _detect_kakao_residual_sentinel

    log_dir = tmp_path / "logs" / "admin"
    log_dir.mkdir(parents=True)

    residuals = _detect_kakao_residual_sentinel(log_dir)

    assert residuals == []
    assert not (tmp_path / "logs" / "kakao_watchdog_anomaly.log").exists()

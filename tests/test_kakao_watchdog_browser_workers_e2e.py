"""BrowserWorkerManager Kakao watchdog lifecycle coverage."""

from __future__ import annotations

from types import SimpleNamespace


def test_browser_worker_manager_starts_kakao_watchdog_and_clears_residual_sentinel(tmp_path, monkeypatch):
    from scripts.services.browser_worker_runtime import manager as manager_mod
    from scripts.services.browser_worker_runtime.manager import BrowserWorkerManager

    calls: list[list[str]] = []

    def fake_tracked_popen_sync(cmd, **_kwargs):
        calls.append([str(part) for part in cmd])
        return SimpleNamespace(pid=424242)

    monkeypatch.setattr(manager_mod, "is_port_listening", lambda _port: False)
    monkeypatch.setattr(manager_mod, "find_pids_on_port", lambda _port: [])
    monkeypatch.setattr(manager_mod, "is_process_alive", lambda _pid: False)
    monkeypatch.setattr(manager_mod, "read_pid_file", lambda _path: None)
    monkeypatch.setattr(manager_mod, "tracked_popen_sync", fake_tracked_popen_sync)

    def fake_write_pid_file(path, pid):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(pid), encoding="ascii")

    monkeypatch.setattr(manager_mod, "write_pid_file", fake_write_pid_file)

    manager = BrowserWorkerManager()
    manager.pid_dir = tmp_path / ".pids"
    manager.log_dir = tmp_path / "logs" / "admin"
    manager.pid_dir.mkdir(parents=True)
    manager.log_dir.mkdir(parents=True)
    manager.legacy_pid_files = []
    manager.workers = [
        worker
        for worker in manager.workers
        if worker["name"] == "Kakao Notification Watchdog"
    ]

    stale_sentinel = manager.log_dir / "kakao_watchdog_alive_999.flag"
    stale_sentinel.write_text("alive", encoding="utf-8")

    manager.start()

    assert calls, "Kakao watchdog process should be started through BrowserWorkerManager.start()"
    assert any("kakao-notification-watchdog.ps1" in part for part in calls[0])
    assert "monitorpage-wdog-kakao.exe" in calls[0][0] or calls[0][0] == "powershell.exe"
    assert (manager.pid_dir / "kakao_notification_watchdog_admin.pid").read_text(encoding="ascii") == "424242"
    assert not stale_sentinel.exists()
    assert (tmp_path / "logs" / "kakao_watchdog_anomaly.log").exists()

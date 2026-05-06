from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.runtime_fingerprint import (
    WORKER_SOURCE_FILES,
    build_runtime_fingerprint_snapshot,
    get_runtime_fingerprint_snapshot,
    get_worker_runtime_fingerprint_snapshot,
)
from scripts.services.browser_worker_runtime import api_actions


class _Response:
    def __init__(self, status: int = 200, payload: bytes = b"{}"):
        self.status = status
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _restart_target(tmp_path: Path) -> api_actions.RestartApiTarget:
    return api_actions.RestartApiTarget(
        api_port=8001,
        app_mode="admin",
        pid_suffix="_admin",
        pid_file=tmp_path / ".pids" / "api_admin.pid",
        service_name="MonitorPage-Admin",
    )


def _manager_with_log_dir(tmp_path: Path) -> MagicMock:
    log_dir = tmp_path / "logs" / "admin"
    log_dir.mkdir(parents=True, exist_ok=True)
    manager = MagicMock()
    manager.log_dir = log_dir
    return manager


def _write_service_log(log_dir: Path, lines: list[str]) -> Path:
    path = log_dir / "service_runner_20260504_113328.log"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_death_log(log_dir: Path, entries: list[dict[str, object]]) -> Path:
    path = log_dir / "death_log.json"
    path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
    return path


def _death_entry(
    timestamp: datetime,
    *,
    cause: str,
    uptime_seconds: int = 0,
    last_request: str | None = None,
) -> dict[str, object]:
    return {
        "timestamp": timestamp.isoformat(timespec="seconds"),
        "pid": 1234,
        "event": "death",
        "cause": cause,
        "exit_code": 1,
        "uptime_seconds": uptime_seconds,
        "details": "fixture",
        "last_request": last_request,
    }


def _runtime_success_urlopen(expected_fingerprint: str):
    def fake_urlopen(url, timeout=0, **kwargs):
        if "runtime-fingerprint" in url:
            return _Response(200, json.dumps({"runtime_fingerprint": expected_fingerprint}).encode("utf-8"))
        raise AssertionError(f"unexpected url: {url}")

    return fake_urlopen


def test_runtime_fingerprint_changes_when_source_or_mode_changes(tmp_path: Path):
    root = tmp_path
    source_file = root / "app" / "routes" / "system.py"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("alpha", encoding="utf-8")

    admin_snapshot = build_runtime_fingerprint_snapshot(
        project_root=root,
        app_mode="admin",
        source_files=["app/routes/system.py"],
        pid=111,
        cwd=root,
        python_executable="python.exe",
    )
    public_snapshot = build_runtime_fingerprint_snapshot(
        project_root=root,
        app_mode="public",
        source_files=["app/routes/system.py"],
        pid=222,
        cwd=root,
        python_executable="python.exe",
    )
    source_file.write_text("bravo", encoding="utf-8")
    changed_source_snapshot = build_runtime_fingerprint_snapshot(
        project_root=root,
        app_mode="admin",
        source_files=["app/routes/system.py"],
        pid=333,
        cwd=root,
        python_executable="python.exe",
    )

    assert admin_snapshot["source_fingerprint"] == public_snapshot["source_fingerprint"]
    assert admin_snapshot["runtime_fingerprint"] != public_snapshot["runtime_fingerprint"]
    assert admin_snapshot["source_fingerprint"] != changed_source_snapshot["source_fingerprint"]


def test_runtime_fingerprint_snapshot_reflects_current_app_mode(monkeypatch):
    monkeypatch.setenv("APP_MODE", "admin")
    admin_snapshot = get_runtime_fingerprint_snapshot()
    monkeypatch.setenv("APP_MODE", "public")
    public_snapshot = get_runtime_fingerprint_snapshot()

    assert admin_snapshot["app_mode"] == "admin"
    assert public_snapshot["app_mode"] == "public"
    assert admin_snapshot["runtime_fingerprint"] != public_snapshot["runtime_fingerprint"]


def test_worker_runtime_fingerprint_includes_instagram_scheduler_sources():
    assert "app/worker/main.py" in WORKER_SOURCE_FILES
    assert "app/worker/scheduled_worker.py" in WORKER_SOURCE_FILES
    assert "app/modules/instagram/services/scheduler.py" in WORKER_SOURCE_FILES
    assert "app/modules/instagram/schedulers/feed_schedule.py" in WORKER_SOURCE_FILES


def test_worker_runtime_source_fingerprint_changes_when_scheduler_source_changes(tmp_path: Path):
    worker_main = tmp_path / "app" / "worker" / "main.py"
    scheduler_source = tmp_path / "app" / "modules" / "instagram" / "services" / "scheduler.py"
    worker_main.parent.mkdir(parents=True, exist_ok=True)
    scheduler_source.parent.mkdir(parents=True, exist_ok=True)
    worker_main.write_text("worker", encoding="utf-8")
    scheduler_source.write_text("alpha", encoding="utf-8")

    first = build_runtime_fingerprint_snapshot(
        project_root=tmp_path,
        app_mode="admin",
        source_files=["app/worker/main.py", "app/modules/instagram/services/scheduler.py"],
        pid=111,
        cwd=tmp_path,
        python_executable="python.exe",
    )
    scheduler_source.write_text("bravo", encoding="utf-8")
    second = build_runtime_fingerprint_snapshot(
        project_root=tmp_path,
        app_mode="admin",
        source_files=["app/worker/main.py", "app/modules/instagram/services/scheduler.py"],
        pid=111,
        cwd=tmp_path,
        python_executable="python.exe",
    )

    assert first["source_fingerprint"] != second["source_fingerprint"]


def test_get_worker_runtime_fingerprint_snapshot_uses_worker_source_files():
    snapshot = get_worker_runtime_fingerprint_snapshot()

    paths = [item["path"] for item in snapshot["source_files"]]
    for expected in WORKER_SOURCE_FILES:
        assert expected in paths


def test_restart_api_waits_for_runtime_fingerprint_match(tmp_path: Path):
    manager = MagicMock()
    manager.api_port = 8001
    manager.pid_suffix = "_admin"
    manager.pid_dir = tmp_path / ".pids"
    manager._check_wmi_health.return_value = True

    expected_snapshot = build_runtime_fingerprint_snapshot(app_mode="admin")
    expected_fingerprint = str(expected_snapshot["runtime_fingerprint"])

    runtime_calls = {"count": 0}

    def fake_urlopen(request, timeout=0, **kwargs):
        url = getattr(request, "full_url", request)
        if "__local/api-gate/close" in url:
            return _Response(200, b"{}")
        if "self-restart" in url:
            return _Response(200, b"{}")
        if "runtime-fingerprint" in url:
            runtime_calls["count"] += 1
            payload = {"runtime_fingerprint": "mismatch" if runtime_calls["count"] == 1 else expected_fingerprint}
            return _Response(200, json.dumps(payload).encode("utf-8"))
        raise AssertionError(f"status fallback should not be used once runtime fingerprint responds: {url}")

    with patch.object(api_actions.time, "sleep", return_value=None), patch.object(
        api_actions.urllib.request, "urlopen", side_effect=fake_urlopen
    ), patch.object(api_actions, "build_runtime_fingerprint_snapshot", return_value=expected_snapshot):
        api_actions.restart_api(manager)

    assert runtime_calls["count"] >= 2


def test_restart_api_success_output_includes_service_log_window_T3(tmp_path: Path):
    manager = _manager_with_log_dir(tmp_path)
    manager.api_port = 8001
    manager.pid_suffix = "_admin"
    manager.pid_dir = tmp_path / ".pids"
    manager._check_wmi_health.return_value = True
    _write_service_log(
        manager.log_dir,
        [
            "[2026-05-04 11:33:28] Monitor Page Service Starting",
            "[2026-05-04 11:33:35] API Server starting on port 8001",
        ],
    )
    expected_snapshot = build_runtime_fingerprint_snapshot(app_mode="admin")
    expected_fingerprint = str(expected_snapshot["runtime_fingerprint"])
    printed: list[str] = []

    def fake_urlopen(request, timeout=0, **kwargs):
        url = getattr(request, "full_url", request)
        if "__local/api-gate/close" in url:
            return _Response(200, b"{}")
        if "self-restart" in url:
            return _Response(200, b"{}")
        if "runtime-fingerprint" in url:
            return _Response(200, json.dumps({"runtime_fingerprint": expected_fingerprint}).encode("utf-8"))
        raise AssertionError(f"unexpected url: {url}")

    with patch.object(api_actions.time, "sleep", return_value=None), patch.object(
        api_actions.urllib.request,
        "urlopen",
        side_effect=fake_urlopen,
    ), patch.object(api_actions, "build_runtime_fingerprint_snapshot", return_value=expected_snapshot), patch.object(
        api_actions,
        "cprint",
        side_effect=lambda message, *args, **kwargs: printed.append(str(message)),
    ):
        assert api_actions.restart_api(manager) is True

    assert any("service_log_window=" in message for message in printed)


def test_restart_api_public_uses_extended_readiness_timeout(tmp_path: Path):
    manager = MagicMock()
    manager.pid_dir = tmp_path / ".pids"
    manager._check_wmi_health.return_value = True
    expected_snapshot = build_runtime_fingerprint_snapshot(app_mode="public")
    readiness = api_actions.RestartApiReadinessResult(
        healthy=True,
        reason="runtime_fingerprint_matched",
        elapsed_seconds=75,
    )

    def fake_urlopen(request, timeout=0, **kwargs):
        url = getattr(request, "full_url", request)
        if "__local/api-gate/close" in url:
            raise urllib.error.URLError("public frontend gate unavailable")
        if "self-restart" in url:
            return _Response(200, b"{}")
        raise AssertionError(f"unexpected url: {url}")

    with patch.object(api_actions.urllib.request, "urlopen", side_effect=fake_urlopen), patch.object(
        api_actions,
        "build_runtime_fingerprint_snapshot",
        return_value=expected_snapshot,
    ), patch.object(api_actions, "_wait_for_restart_api_readiness", return_value=readiness) as mock_wait:
        assert api_actions.restart_api(manager, public=True) is True

    assert mock_wait.call_args.kwargs["timeout_seconds"] == api_actions.PUBLIC_READINESS_TIMEOUT_SECONDS


def test_restart_api_falls_back_to_status_when_runtime_fingerprint_missing(tmp_path: Path):
    manager = MagicMock()
    manager.api_port = 8001
    manager.pid_suffix = "_admin"
    manager.pid_dir = tmp_path / ".pids"
    manager._check_wmi_health.return_value = True

    def fake_urlopen(request, timeout=0, **kwargs):
        url = getattr(request, "full_url", request)
        if "__local/api-gate/close" in url:
            return _Response(200, b"{}")
        if "self-restart" in url:
            return _Response(200, b"{}")
        if "runtime-fingerprint" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)
        if "system/liveness" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)
        if "system/status" in url:
            return _Response(200, b"{}")
        raise AssertionError(f"unexpected url: {url}")

    with patch.object(api_actions.time, "sleep", return_value=None), patch.object(
        api_actions.urllib.request, "urlopen", side_effect=fake_urlopen
    ), patch.object(api_actions, "build_runtime_fingerprint_snapshot", return_value={"runtime_fingerprint": "expected"}):
        api_actions.restart_api(manager)


def test_restart_api_calls_gate_close_before_self_restart(tmp_path: Path):
    manager = MagicMock()
    manager.api_port = 8001
    manager.pid_suffix = "_admin"
    manager.pid_dir = tmp_path / ".pids"
    manager._check_wmi_health.return_value = True

    expected_snapshot = build_runtime_fingerprint_snapshot(app_mode="admin")
    expected_fingerprint = str(expected_snapshot["runtime_fingerprint"])
    calls: list[str] = []

    def fake_urlopen(request, timeout=0, **kwargs):
        url = getattr(request, "full_url", request)
        calls.append(url)
        if "__local/api-gate/close" in url:
            return _Response(200, b"{}")
        if "self-restart" in url:
            return _Response(200, b"{}")
        if "runtime-fingerprint" in url:
            return _Response(200, json.dumps({"runtime_fingerprint": expected_fingerprint}).encode("utf-8"))
        raise AssertionError(f"unexpected url: {url}")

    with patch.object(api_actions.time, "sleep", return_value=None), patch.object(
        api_actions.urllib.request, "urlopen", side_effect=fake_urlopen
    ), patch.object(api_actions, "build_runtime_fingerprint_snapshot", return_value=expected_snapshot):
        api_actions.restart_api(manager)

    assert next(i for i, url in enumerate(calls) if "__local/api-gate/close" in url) < next(
        i for i, url in enumerate(calls) if "self-restart" in url
    )


def test_restart_api_continues_on_gate_close_failure(tmp_path: Path):
    manager = MagicMock()
    manager.api_port = 8001
    manager.pid_suffix = "_admin"
    manager.pid_dir = tmp_path / ".pids"
    manager._check_wmi_health.return_value = True

    expected_snapshot = build_runtime_fingerprint_snapshot(app_mode="admin")
    expected_fingerprint = str(expected_snapshot["runtime_fingerprint"])
    self_restart_called = False

    def fake_urlopen(request, timeout=0, **kwargs):
        nonlocal self_restart_called
        url = getattr(request, "full_url", request)
        if "__local/api-gate/close" in url:
            raise urllib.error.URLError("gate offline")
        if "self-restart" in url:
            self_restart_called = True
            return _Response(200, b"{}")
        if "runtime-fingerprint" in url:
            return _Response(200, json.dumps({"runtime_fingerprint": expected_fingerprint}).encode("utf-8"))
        raise AssertionError(f"unexpected url: {url}")

    with patch.object(api_actions.time, "sleep", return_value=None), patch.object(
        api_actions.urllib.request, "urlopen", side_effect=fake_urlopen
    ), patch.object(api_actions, "build_runtime_fingerprint_snapshot", return_value=expected_snapshot):
        api_actions.restart_api(manager)

    assert self_restart_called is True


def test_close_api_gate_sends_correct_payload():
    captured = {}

    def fake_urlopen(request, timeout=0, **kwargs):
        captured["url"] = request.full_url
        captured["data"] = request.data
        captured["timeout"] = timeout
        captured["content_type"] = request.headers["Content-type"]
        return _Response(200, b"{}")

    with patch.object(api_actions.urllib.request, "urlopen", side_effect=fake_urlopen):
        api_actions._close_api_gate(8001)

    assert captured["url"] == "http://127.0.0.1:6101/__local/api-gate/close"
    assert json.loads(captured["data"].decode("utf-8")) == {
        "api_port": 8001,
        "reason": "browser_workers restart-api",
    }
    assert captured["timeout"] == 5
    assert captured["content_type"] == "application/json"


def test_close_api_gate_port_mapping():
    urls: list[str] = []

    def fake_urlopen(request, timeout=0, **kwargs):
        urls.append(request.full_url)
        return _Response(200, b"{}")

    with patch.object(api_actions.urllib.request, "urlopen", side_effect=fake_urlopen):
        api_actions._close_api_gate(8000)
        api_actions._close_api_gate(8001)

    assert urls == [
        "http://127.0.0.1:6100/__local/api-gate/close",
        "http://127.0.0.1:6101/__local/api-gate/close",
    ]


def test_fetch_json_with_host_fallback_uses_localhost_when_127_fails():
    calls: list[str] = []

    def fake_urlopen(url, timeout=0, **kwargs):
        calls.append(url)
        if "127.0.0.1" in url:
            raise urllib.error.URLError("loopback refused")
        return _Response(200, b'{"status":"ok"}')

    with patch.object(api_actions.urllib.request, "urlopen", side_effect=fake_urlopen):
        result = api_actions._fetch_json_with_host_fallback(8001, "/api/v1/system/liveness")

    assert result.data == {"status": "ok"}
    assert result.url == "http://localhost:8001/api/v1/system/liveness"
    assert result.fallback_used is True
    assert calls == [
        "http://127.0.0.1:8001/api/v1/system/liveness",
        "http://localhost:8001/api/v1/system/liveness",
    ]


def test_restart_api_timeout_classifies_slow_app_import_as_non_hard_failure(tmp_path: Path):
    log_dir = tmp_path / "logs" / "admin"
    log_dir.mkdir(parents=True)
    (log_dir / "service_runner_20260504_113328.log").write_text(
        "\n".join(
            [
                "[2026-05-04 11:33:28] Monitor Page Service Starting",
                "[2026-05-04 11:33:29] Importing app.config...",
                "[2026-05-04 11:33:30] Importing app.main...",
            ]
        ),
        encoding="utf-8",
    )
    manager = MagicMock()
    manager.log_dir = log_dir
    manager.find_pids_on_port.return_value = []
    manager.read_pid_file.return_value = None
    target = api_actions.RestartApiTarget(
        api_port=8001,
        app_mode="admin",
        pid_suffix="_admin",
        pid_file=tmp_path / ".pids" / "api_admin.pid",
        service_name="MonitorPage-Admin",
    )
    result = api_actions._classify_restart_api_timeout(
        manager,
        target,
        elapsed_seconds=60,
        last_error="connection refused",
    )

    assert result.reason == "cold_import_in_progress"
    assert result.hard_failure is False
    assert result.service_log_window and "service_runner_20260504_113328.log" in result.service_log_window
    assert result.evidence == result.service_log_window


def test_restart_api_timeout_classifies_startup_exception_as_hard_failure(tmp_path: Path):
    log_dir = tmp_path / "logs" / "admin"
    log_dir.mkdir(parents=True)
    (log_dir / "service_runner_20260504_113328.log").write_text(
        "\n".join(
            [
                "[2026-05-04 11:33:28] Monitor Page Service Starting",
                "[2026-05-04 11:33:31] Service failed: RuntimeError('boom')",
                "Traceback (most recent call last)",
            ]
        ),
        encoding="utf-8",
    )
    manager = MagicMock()
    manager.log_dir = log_dir
    target = api_actions.RestartApiTarget(
        api_port=8001,
        app_mode="admin",
        pid_suffix="_admin",
        pid_file=tmp_path / ".pids" / "api_admin.pid",
        service_name="MonitorPage-Admin",
    )

    result = api_actions._classify_restart_api_timeout(
        manager,
        target,
        elapsed_seconds=60,
        last_error="connection refused",
    )

    assert result.reason == "startup_exception_seen_before_ready"
    assert result.hard_failure is True


@pytest.mark.parametrize(
    "failure_line",
    [
        "[2026-05-04 11:33:31] Service failed: ModuleNotFoundError(\"No module named 'app.lifespan'\")",
        "[2026-05-04 11:33:31] Service failed: ImportError('cannot import name router')",
        "[2026-05-04 11:33:31] Service failed: RuntimeError('arbitrary startup boom')",
    ],
)
def test_restart_api_liveness_success_with_any_startup_exception_is_hard_failure_E(
    tmp_path: Path,
    failure_line: str,
):
    manager = _manager_with_log_dir(tmp_path)
    target = _restart_target(tmp_path)
    _write_service_log(
        manager.log_dir,
        [
            "[2026-05-04 11:33:28] Monitor Page Service Starting",
            failure_line,
        ],
    )
    expected_fingerprint = "expected-runtime"

    with patch.object(api_actions.time, "sleep", return_value=None), patch.object(
        api_actions.urllib.request,
        "urlopen",
        side_effect=_runtime_success_urlopen(expected_fingerprint),
    ):
        result = api_actions._wait_for_restart_api_readiness(
            manager,
            target,
            expected_fingerprint=expected_fingerprint,
            expected_source_fingerprint="expected-source",
            timeout_seconds=5,
            poll_seconds=5,
        )

    assert result.healthy is False
    assert result.reason == "startup_exception_seen_before_ready"
    assert result.hard_failure is True
    assert result.service_log_window and "Monitor Page Service Starting" in result.service_log_window
    assert result.failure_evidence and "service_log=" in result.failure_evidence


def test_restart_api_zero_uptime_startup_death_after_restart_is_hard_failure_E(tmp_path: Path):
    manager = _manager_with_log_dir(tmp_path)
    target = _restart_target(tmp_path)
    restart_at = datetime(2026, 5, 4, 11, 33, 28)
    _write_service_log(
        manager.log_dir,
        [
            "[2026-05-04 11:33:28] Monitor Page Service Starting",
            "[2026-05-04 11:33:35] API Server starting on port 8001",
        ],
    )
    _write_death_log(
        manager.log_dir,
        [
            _death_entry(restart_at + timedelta(seconds=1), cause="python_exception", uptime_seconds=0),
        ],
    )
    expected_fingerprint = "expected-runtime"

    with patch.object(api_actions.time, "sleep", return_value=None), patch.object(
        api_actions.urllib.request,
        "urlopen",
        side_effect=_runtime_success_urlopen(expected_fingerprint),
    ):
        result = api_actions._wait_for_restart_api_readiness(
            manager,
            target,
            expected_fingerprint=expected_fingerprint,
            expected_source_fingerprint="expected-source",
            timeout_seconds=5,
            poll_seconds=5,
        )

    assert result.healthy is False
    assert result.reason == "startup_death_seen_before_ready"
    assert result.hard_failure is True
    assert result.death_log_window and "python_exception" in result.death_log_window
    assert result.failure_evidence and "death_log=" in result.failure_evidence


def test_restart_api_normal_shutdown_zero_uptime_is_not_hard_failure_B(tmp_path: Path):
    manager = _manager_with_log_dir(tmp_path)
    target = _restart_target(tmp_path)
    restart_at = datetime(2026, 5, 4, 11, 33, 28)
    _write_service_log(
        manager.log_dir,
        [
            "[2026-05-04 11:33:28] Monitor Page Service Starting",
            "[2026-05-04 11:33:35] API Server starting on port 8001",
        ],
    )
    _write_death_log(
        manager.log_dir,
        [
            _death_entry(
                restart_at + timedelta(seconds=1),
                cause="normal_shutdown",
                uptime_seconds=0,
                last_request="/api/v1/ready",
            ),
        ],
    )
    expected_fingerprint = "expected-runtime"

    with patch.object(api_actions.time, "sleep", return_value=None), patch.object(
        api_actions.urllib.request,
        "urlopen",
        side_effect=_runtime_success_urlopen(expected_fingerprint),
    ):
        result = api_actions._wait_for_restart_api_readiness(
            manager,
            target,
            expected_fingerprint=expected_fingerprint,
            expected_source_fingerprint="expected-source",
            timeout_seconds=5,
            poll_seconds=5,
        )

    assert result.healthy is True
    assert result.reason == "runtime_fingerprint_matched"
    assert result.hard_failure is False
    assert result.service_log_window and "service_runner_20260504_113328.log" in result.service_log_window
    assert result.death_log_window and "normal_shutdown" in result.death_log_window


def test_restart_api_cold_import_in_progress_is_not_hard_failure_B(tmp_path: Path):
    manager = _manager_with_log_dir(tmp_path)
    target = _restart_target(tmp_path)
    _write_service_log(
        manager.log_dir,
        [
            "[2026-05-04 11:33:28] Monitor Page Service Starting",
            "[2026-05-04 11:33:29] Importing app.config...",
            "[2026-05-04 11:33:30] Importing app.main...",
        ],
    )
    expected_fingerprint = "expected-runtime"

    with patch.object(api_actions.time, "sleep", return_value=None), patch.object(
        api_actions.urllib.request,
        "urlopen",
        side_effect=_runtime_success_urlopen(expected_fingerprint),
    ):
        result = api_actions._wait_for_restart_api_readiness(
            manager,
            target,
            expected_fingerprint=expected_fingerprint,
            expected_source_fingerprint="expected-source",
            timeout_seconds=5,
            poll_seconds=5,
        )

    assert result.healthy is True
    assert result.reason == "runtime_fingerprint_matched"
    assert result.hard_failure is False
    assert result.service_log_window and "Importing app.main" in result.service_log_window


def test_restart_api_old_failure_outside_restart_window_is_ignored_B(tmp_path: Path):
    manager = _manager_with_log_dir(tmp_path)
    target = _restart_target(tmp_path)
    _write_service_log(
        manager.log_dir,
        [
            "[2026-05-04 11:20:00] Monitor Page Service Starting",
            "[2026-05-04 11:20:01] Service failed: RuntimeError('old failure')",
            "[2026-05-04 11:33:28] Monitor Page Service Starting",
            "[2026-05-04 11:33:35] API Server starting on port 8001",
        ],
    )
    expected_fingerprint = "expected-runtime"

    with patch.object(api_actions.time, "sleep", return_value=None), patch.object(
        api_actions.urllib.request,
        "urlopen",
        side_effect=_runtime_success_urlopen(expected_fingerprint),
    ):
        result = api_actions._wait_for_restart_api_readiness(
            manager,
            target,
            expected_fingerprint=expected_fingerprint,
            expected_source_fingerprint="expected-source",
            timeout_seconds=5,
            poll_seconds=5,
        )

    assert result.healthy is True
    assert result.reason == "runtime_fingerprint_matched"
    assert result.service_log_window
    assert "old failure" not in result.service_log_window


def test_restart_api_old_failure_in_older_log_file_is_ignored_B(tmp_path: Path):
    manager = _manager_with_log_dir(tmp_path)
    target = _restart_target(tmp_path)
    (manager.log_dir / "service_runner_20260504_112000.log").write_text(
        "\n".join(
            [
                "[2026-05-04 11:20:00] Monitor Page Service Starting",
                "[2026-05-04 11:20:01] Service failed: RuntimeError('old failure')",
                "Traceback (most recent call last)",
            ]
        ),
        encoding="utf-8",
    )
    (manager.log_dir / "service_runner_20260504_113328.log").write_text(
        "\n".join(
            [
                "[2026-05-04 11:33:28] Monitor Page Service Starting",
                "[2026-05-04 11:33:35] API Server starting on port 8001",
            ]
        ),
        encoding="utf-8",
    )
    expected_fingerprint = "expected-runtime"

    with patch.object(api_actions.time, "sleep", return_value=None), patch.object(
        api_actions.urllib.request,
        "urlopen",
        side_effect=_runtime_success_urlopen(expected_fingerprint),
    ):
        result = api_actions._wait_for_restart_api_readiness(
            manager,
            target,
            expected_fingerprint=expected_fingerprint,
            expected_source_fingerprint="expected-source",
            timeout_seconds=5,
            poll_seconds=5,
        )

    assert result.healthy is True
    assert result.reason == "runtime_fingerprint_matched"
    assert result.service_log_window
    assert "service_runner_20260504_113328.log" in result.service_log_window
    assert "old failure" not in result.service_log_window


def test_restart_api_public_target_uses_public_service_log_window(tmp_path: Path):
    manager = _manager_with_log_dir(tmp_path)
    admin_log = manager.log_dir / "service_runner_20260504_113328.log"
    admin_log.write_text(
        "\n".join(
            [
                "[2026-05-04 11:33:28] Monitor Page Service Starting",
                "[2026-05-04 11:33:35] API Server starting on port 8001",
            ]
        ),
        encoding="utf-8",
    )
    public_log = manager.log_dir.parent / "service_MonitorPage-Public.log"
    public_log.write_text(
        "\n".join(
            [
                "[2026-05-04 11:40:28] Monitor Page Service Starting",
                "[2026-05-04 11:40:35] API Server starting on port 8000",
            ]
        ),
        encoding="utf-8",
    )
    target = api_actions.RestartApiTarget(
        api_port=8000,
        app_mode="public",
        pid_suffix="",
        pid_file=tmp_path / ".pids" / "api.pid",
        service_name="MonitorPage-Public",
    )

    result = api_actions._scan_restart_window_failures(manager, target)

    assert result.service_log_window
    assert "service_MonitorPage-Public.log" in result.service_log_window
    assert "8000" in result.service_log_window
    assert "8001" not in result.service_log_window


def test_restart_api_filesystem_log_fixture_integration_T3(tmp_path: Path):
    manager = _manager_with_log_dir(tmp_path)
    target = _restart_target(tmp_path)
    restart_at = datetime(2026, 5, 4, 11, 33, 28)
    _write_service_log(
        manager.log_dir,
        [
            "[2026-05-04 11:33:28] Monitor Page Service Starting",
            "[2026-05-04 11:33:35] API Server starting on port 8001",
        ],
    )
    _write_death_log(
        manager.log_dir,
        [
            _death_entry(restart_at - timedelta(minutes=5), cause="python_exception", uptime_seconds=0),
            _death_entry(restart_at + timedelta(seconds=2), cause="external_kill", uptime_seconds=0),
        ],
    )

    def fake_urlopen(url, timeout=0, **kwargs):
        if "runtime-fingerprint" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)
        if "system/liveness" in url:
            return _Response(200, b'{"status":"ok"}')
        raise AssertionError(f"unexpected url: {url}")

    with patch.object(api_actions.time, "sleep", return_value=None), patch.object(
        api_actions.urllib.request,
        "urlopen",
        side_effect=fake_urlopen,
    ):
        result = api_actions._wait_for_restart_api_readiness(
            manager,
            target,
            expected_fingerprint="expected-runtime",
            expected_source_fingerprint="expected-source",
            timeout_seconds=5,
            poll_seconds=5,
        )

    assert result.healthy is False
    assert result.reason == "startup_death_seen_before_ready"
    assert result.service_log_window and "Monitor Page Service Starting" in result.service_log_window
    assert result.death_log_window and "external_kill" in result.death_log_window
    assert result.failure_evidence and "external_kill" in result.failure_evidence


def test_restart_api_cli_returns_nonzero_for_hard_restart_failure(monkeypatch):
    from scripts.services.browser_worker_runtime import cli

    class FakeManager:
        def start(self) -> bool:
            return True

        def stop(self) -> bool:
            return True

        def restart(self) -> bool:
            return True

        def status(self) -> bool:
            return True

        def restart_api(self, public: bool = False) -> bool:
            assert public is True
            return False

        def redis_status(self) -> bool:
            return True

        def redis_restart(self) -> bool:
            return True

        def redis_cleanup(self) -> bool:
            return True

        def restart_listener(self) -> bool:
            return True

        def restart_infra(self, target: str) -> bool:
            return True

        def restart_frontend(self, public: bool = False) -> bool:
            return True

    monkeypatch.setattr(cli, "assert_repo_root_checkout", lambda: None)

    assert cli.main(FakeManager, ["restart-api", "--public"]) == 1

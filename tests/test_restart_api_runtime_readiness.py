from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

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

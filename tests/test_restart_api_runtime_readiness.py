from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.runtime_fingerprint import build_runtime_fingerprint_snapshot
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


def test_restart_api_waits_for_runtime_fingerprint_match(tmp_path: Path):
    manager = MagicMock()
    manager.api_port = 8001
    manager.pid_suffix = "_admin"
    manager.pid_dir = tmp_path / ".pids"
    manager._check_wmi_health.return_value = True

    expected_snapshot = build_runtime_fingerprint_snapshot(app_mode="admin")
    expected_source_fingerprint = str(expected_snapshot["source_fingerprint"])

    runtime_calls = {"count": 0}

    def fake_urlopen(request, timeout=0, **kwargs):
        url = getattr(request, "full_url", request)
        if "self-restart" in url:
            return _Response(200, b"{}")
        if "runtime-fingerprint" in url:
            runtime_calls["count"] += 1
            payload = {
                "runtime_fingerprint": "runtime-mismatch",
                "source_fingerprint": "source-mismatch" if runtime_calls["count"] == 1 else expected_source_fingerprint,
            }
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
        if "self-restart" in url:
            return _Response(200, b"{}")
        if "runtime-fingerprint" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)
        if "system/status" in url:
            return _Response(200, b"{}")
        raise AssertionError(f"unexpected url: {url}")

    with patch.object(api_actions.time, "sleep", return_value=None), patch.object(
        api_actions.urllib.request, "urlopen", side_effect=fake_urlopen
    ), patch.object(api_actions, "build_runtime_fingerprint_snapshot", return_value={"source_fingerprint": "expected"}):
        api_actions.restart_api(manager)


def test_restart_api_does_not_fall_back_to_status_after_runtime_mismatch(tmp_path: Path):
    manager = MagicMock()
    manager.api_port = 8001
    manager.pid_suffix = "_admin"
    manager.pid_dir = tmp_path / ".pids"
    manager._check_wmi_health.return_value = True

    status_calls = {"count": 0}
    fingerprint_calls = {"count": 0}

    def fake_urlopen(request, timeout=0, **kwargs):
        url = getattr(request, "full_url", request)
        if "self-restart" in url:
            return _Response(200, b"{}")
        if "runtime-fingerprint" in url:
            fingerprint_calls["count"] += 1
            if fingerprint_calls["count"] == 1:
                return _Response(200, b'{"runtime_fingerprint":"runtime-mismatch","source_fingerprint":"mismatch"}')
            raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)
        if "system/status" in url:
            status_calls["count"] += 1
            return _Response(200, b"{}")
        raise AssertionError(f"unexpected url: {url}")

    with patch.object(api_actions.time, "sleep", return_value=None), patch.object(
        api_actions.urllib.request, "urlopen", side_effect=fake_urlopen
    ), patch.object(api_actions, "build_runtime_fingerprint_snapshot", return_value={"source_fingerprint": "expected"}):
        api_actions.restart_api(manager)

    assert fingerprint_calls["count"] >= 2
    assert status_calls["count"] == 0


def test_restart_api_logs_port_pid_fallback_when_self_restart_unavailable(tmp_path: Path, capsys):
    manager = MagicMock()
    manager.api_port = 8001
    manager.pid_suffix = "_admin"
    manager.pid_dir = tmp_path / ".pids"
    manager._check_wmi_health.return_value = True

    def fake_urlopen(request, timeout=0, **kwargs):
        url = getattr(request, "full_url", request)
        if "self-restart" in url:
            raise OSError("self restart unavailable")
        if "runtime-fingerprint" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)
        if "system/status" in url:
            return _Response(200, b"{}")
        raise AssertionError(f"unexpected url: {url}")

    with patch.object(api_actions.time, "sleep", return_value=None), patch.object(
        api_actions.urllib.request, "urlopen", side_effect=fake_urlopen
    ), patch.object(api_actions, "build_runtime_fingerprint_snapshot", return_value={"source_fingerprint": "expected"}), patch(
        "scripts.services.browser_worker_runtime.manager.find_pids_on_port", return_value=[4321, 4322]
    ), patch(
        "scripts.services.browser_worker_runtime.manager.kill_pid", return_value=True
    ):
        api_actions.restart_api(manager)

    captured = capsys.readouterr()
    assert "Active API port PIDs detected: [4321, 4322]" in captured.out
    assert "Killing API process (PID: 4321)" in captured.out
    assert "Killing API process (PID: 4322)" in captured.out


def test_restart_api_logs_stale_pid_fallback_when_port_is_dead(tmp_path: Path, capsys):
    manager = MagicMock()
    manager.api_port = 8001
    manager.pid_suffix = "_admin"
    manager.pid_dir = tmp_path / ".pids"
    manager._check_wmi_health.return_value = True
    manager._nssm_restart_elevated.return_value = True

    def fake_urlopen(request, timeout=0, **kwargs):
        url = getattr(request, "full_url", request)
        if "self-restart" in url:
            raise OSError("self restart unavailable")
        if "runtime-fingerprint" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)
        if "system/status" in url:
            return _Response(200, b"{}")
        raise AssertionError(f"unexpected url: {url}")

    with patch.object(api_actions.time, "sleep", return_value=None), patch.object(
        api_actions.urllib.request, "urlopen", side_effect=fake_urlopen
    ), patch.object(api_actions, "build_runtime_fingerprint_snapshot", return_value={"source_fingerprint": "expected"}), patch(
        "scripts.services.browser_worker_runtime.manager.find_pids_on_port", return_value=[]
    ), patch(
        "scripts.services.browser_worker_runtime.manager.read_pid_file", return_value=9999
    ), patch(
        "scripts.services.browser_worker_runtime.manager.is_process_alive", return_value=True
    ):
        api_actions.restart_api(manager)

    captured = capsys.readouterr()
    assert "Service runner alive (PID: 9999) but API port dead" in captured.out

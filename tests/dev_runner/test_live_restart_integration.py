"""http_live restart-api integration tests.

These tests exercise the real Admin API restart path against the live
localhost:8001 service.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest
import requests

from app.core.runtime_fingerprint import build_runtime_fingerprint_snapshot
from tests.dev_runner._path_helpers import get_repo_root

pytestmark = pytest.mark.http_live

PROJECT_ROOT = get_repo_root()
BROWSER_WORKERS = PROJECT_ROOT / "scripts" / "services" / "browser_workers.py"
BASE_URL = "http://localhost:8001"


def _wait_for_runtime_fingerprint(timeout: float = 120.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            resp = requests.get(f"{BASE_URL}/api/v1/system/runtime-fingerprint", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("runtime_fingerprint") and data.get("source_fingerprint"):
                    return data
        except Exception as exc:
            last_error = exc
        time.sleep(2)
    pytest.fail(f"runtime-fingerprint endpoint did not recover within {timeout}s: {last_error}")


def test_restart_api_replaces_live_runtime_with_current_source():
    before = _wait_for_runtime_fingerprint(timeout=10.0)
    expected = build_runtime_fingerprint_snapshot(app_mode="admin")

    result = subprocess.run(
        [sys.executable, str(BROWSER_WORKERS), "restart-api"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr

    after = _wait_for_runtime_fingerprint(timeout=120.0)
    assert after["app_mode"] == expected["app_mode"] == "admin"
    assert after["source_fingerprint"] == expected["source_fingerprint"]
    assert before["source_fingerprint"] == after["source_fingerprint"]
    assert before["runtime_fingerprint"] != after["runtime_fingerprint"]

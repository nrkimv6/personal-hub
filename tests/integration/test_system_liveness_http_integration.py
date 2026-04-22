"""
HTTP integration tests for GET /api/v1/system/liveness

Uses integration_server fixture (live server on port 18001).
Run after merging to main: pytest tests/integration/test_system_liveness_http_integration.py
"""

import re
import time
from pathlib import Path

import pytest

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

pytestmark = pytest.mark.skipif(not HAS_REQUESTS, reason="requests module required")

PROJECT_ROOT = Path(__file__).parent.parent.parent


class TestSystemLivenessHTTP:

    def test_GET_api_v1_system_liveness_live_returns_200(self, integration_server):
        """Live server: GET /api/v1/system/liveness returns 200 with status=='ok'"""
        response = requests.get(
            f"{integration_server}/api/v1/system/liveness", timeout=10
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_GET_api_v1_system_liveness_response_time_under_3s(self, integration_server):
        """Live server: 10 calls average < 3s (30% of probe TimeoutSec 10)"""
        # Use Session for connection reuse to reduce per-request TCP overhead
        sess = requests.Session()
        times = []
        for _ in range(10):
            start = time.perf_counter()
            sess.get(f"{integration_server}/api/v1/system/liveness", timeout=10)
            times.append(time.perf_counter() - start)
        avg = sum(times) / len(times)
        assert avg < 3.0, f"avg response {avg:.3f}s >= 3s (TimeoutSec 10 margin at risk)"

    def test_startup_scripts_urls_match_implemented_route(self):
        """Contract guard: both startup scripts point to /system/liveness"""
        scripts = [
            PROJECT_ROOT / "scripts" / "setup" / "startup-browser-workers.ps1",
            PROJECT_ROOT / "scripts" / "watchdogs" / "startup-api-watchdog.ps1",
        ]
        pattern = re.compile(r"http://localhost:8001/api/v1/system/liveness")
        for script in scripts:
            content = script.read_text(encoding="utf-8")
            assert pattern.search(content), (
                f"{script.name} does not reference /system/liveness — "
                "regression: still pointing at /system/status?"
            )

    def test_startup_probe_timeout_is_at_least_10s(self):
        """Regression guard: both startup scripts use TimeoutSec >= 10"""
        scripts = [
            PROJECT_ROOT / "scripts" / "setup" / "startup-browser-workers.ps1",
            PROJECT_ROOT / "scripts" / "watchdogs" / "startup-api-watchdog.ps1",
        ]
        pattern = re.compile(r"-TimeoutSec\s+(\d+)")
        for script in scripts:
            content = script.read_text(encoding="utf-8")
            matches = pattern.findall(content)
            assert matches, f"{script.name} has no -TimeoutSec directive"
            for val in matches:
                assert int(val) >= 10, (
                    f"{script.name}: -TimeoutSec {val} < 10 (regression: reverted to 3?)"
                )

    def test_auto_update_script_uses_liveness_url(self):
        """Contract guard: auto-update.ps1 probe points to /system/liveness"""
        script = PROJECT_ROOT / "scripts" / "setup" / "auto-update.ps1"
        content = script.read_text(encoding="utf-8")
        pattern = re.compile(r"/api/v1/system/liveness")
        assert pattern.search(content), (
            "auto-update.ps1 does not reference /system/liveness — "
            "regression: still pointing at /system/status?"
        )

    def test_auto_update_probe_timeout_is_at_least_10s(self):
        """Regression guard: auto-update.ps1 liveness probe line uses TimeoutSec >= 10"""
        script = PROJECT_ROOT / "scripts" / "setup" / "auto-update.ps1"
        content = script.read_text(encoding="utf-8")
        liveness_lines = [line for line in content.splitlines() if "/system/liveness" in line]
        assert liveness_lines, "auto-update.ps1 has no /system/liveness reference"
        timeout_pattern = re.compile(r"-TimeoutSec\s+(\d+)")
        for line in liveness_lines:
            m = timeout_pattern.search(line)
            if m:
                assert int(m.group(1)) >= 10, (
                    f"auto-update.ps1 liveness probe: -TimeoutSec {m.group(1)} < 10 "
                    "(regression: reverted to 5?)"
                )

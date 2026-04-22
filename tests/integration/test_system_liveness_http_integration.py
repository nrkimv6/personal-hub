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

    def test_GET_api_v1_system_liveness_response_time_under_2s(self, integration_server):
        """Live server: 10 calls average < 2s (half of probe TimeoutSec 10)"""
        times = []
        for _ in range(10):
            start = time.perf_counter()
            requests.get(f"{integration_server}/api/v1/system/liveness", timeout=10)
            times.append(time.perf_counter() - start)
        avg = sum(times) / len(times)
        assert avg < 2.0, f"avg response {avg:.3f}s >= 2s (TimeoutSec 10 margin at risk)"

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

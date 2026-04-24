"""
T4 E2E smoke: 브라우저 상태 live API 계약 회귀

naver-monitor tab acquire timeout fix 후 worker/browser-status, system/status 계약이
유지되는지 live admin API(localhost:8001)로 확인한다.

- GET /api/v1/worker/browser-status → 200 + schema 유지
- GET /api/v1/system/status → 200 + worker_status/active_tabs/browser_contexts 필드 유지

live worker가 내려가 있으면 skip (false-positive 방지).
/merge-test owner가 main runtime에서만 실행한다.
"""
import pytest
import httpx


BASE = "http://localhost:8001"


def _is_api_up() -> bool:
    try:
        r = httpx.get(f"{BASE}/api/v1/system/liveness", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def skip_if_api_down():
    if not _is_api_up():
        pytest.skip("live API(localhost:8001) 미기동 — skip (false-positive 방지)")


class TestWorkerBrowserStatusLive:
    """GET /api/v1/worker/browser-status 계약 smoke."""

    def test_right_browser_status_returns_200_and_schema(self):
        """R: /api/v1/worker/browser-status → 200 + available/last_heartbeat 필드."""
        r = httpx.get(f"{BASE}/api/v1/worker/browser-status", timeout=10.0)
        assert r.status_code == 200, f"status {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert "available" in data, f"'available' 필드 없음: {data}"
        assert "last_heartbeat" in data, f"'last_heartbeat' 필드 없음: {data}"


class TestSystemStatusLive:
    """GET /api/v1/system/status 계약 smoke."""

    def test_right_system_status_returns_200_and_worker_fields(self):
        """R: /api/v1/system/status → 200 + worker_status/active_tabs/browser_contexts."""
        r = httpx.get(f"{BASE}/api/v1/system/status", timeout=10.0)
        assert r.status_code == 200, f"status {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert "worker_status" in data, f"'worker_status' 필드 없음: {data}"
        assert "active_tabs" in data, f"'active_tabs' 필드 없음: {data}"
        assert "browser_contexts" in data, f"'browser_contexts' 필드 없음: {data}"

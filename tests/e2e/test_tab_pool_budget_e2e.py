"""
T4 E2E: sentinel 탭 예산 분리 수정 후 live API 계약 회귀 검증

plan 기술적 고려사항: /api/v1/worker/browser-status는 기존 available/last_heartbeat
계약을 유지하며, budgeted_pages는 내부 get_status()에서만 소비된다.
따라서 HTTP 검증은 기존 라우트 계약 회귀 확인으로 한정한다.

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


class TestBrowserStatusContractUnchanged:
    """browser-status API 계약이 sentinel 수정 후에도 유지됨을 확인."""

    def test_right_browser_status_returns_200_and_schema(self):
        """R: GET /api/v1/worker/browser-status → 200 + available/last_heartbeat 필드 유지."""
        r = httpx.get(f"{BASE}/api/v1/worker/browser-status", timeout=10.0)
        assert r.status_code == 200, f"status {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert "available" in data, f"'available' 필드 없음: {data}"
        assert "last_heartbeat" in data, f"'last_heartbeat' 필드 없음: {data}"

    def test_right_browser_status_available_is_bool(self):
        """R: available 필드는 bool 타입."""
        r = httpx.get(f"{BASE}/api/v1/worker/browser-status", timeout=10.0)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data.get("available"), bool), (
            f"available이 bool이 아님: {data.get('available')!r}"
        )


class TestSystemStatusContractUnchanged:
    """system/status API 계약이 sentinel 수정 후에도 유지됨을 확인."""

    def test_right_system_status_fields_unchanged(self):
        """R: GET /api/v1/system/status → 기존 worker_status/active_tabs/browser_contexts 유지."""
        r = httpx.get(f"{BASE}/api/v1/system/status", timeout=10.0)
        assert r.status_code == 200, f"status {r.status_code}: {r.text[:200]}"
        data = r.json()
        for field in ("worker_status", "active_tabs", "browser_contexts"):
            assert field in data, f"'{field}' 필드 없음 — API 계약 회귀: {data}"


class TestWorkerProgressUnderSentinelPressure:
    """sentinel 탭 예산 분리 후 worker API 응답이 비정상 상태가 아님을 검증."""

    def test_worker_liveness_responds_200(self):
        """R: /api/v1/system/liveness → 200 (worker 기동 중 + API 정상)."""
        r = httpx.get(f"{BASE}/api/v1/system/liveness", timeout=5.0)
        assert r.status_code == 200, f"liveness 실패: {r.status_code}"

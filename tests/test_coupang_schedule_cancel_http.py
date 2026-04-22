"""
coupang/booking asyncio.shield release_tab — HTTP 통합 테스트 (T5)

실서버(localhost:8001)에서 시스템 상태 API를 통해 active_tabs 카운트가
정상 관리되는지 확인합니다. cancel race 시나리오는 T3/T4에서 커버되며,
이 파일은 live 서버에서 기본 응답 정상 여부를 확인합니다.

실행:
    pytest tests/test_coupang_schedule_cancel_http.py -m http_live -v
"""
import pytest
import httpx

pytestmark = pytest.mark.http_live

BASE_URL = "http://localhost:8001"
STATUS_ENDPOINT = "/api/v1/system/status"
LIVENESS_ENDPOINT = "/api/v1/dev-runner/runners"


def _skip_if_down() -> None:
    try:
        httpx.get(f"{BASE_URL}{STATUS_ENDPOINT}", timeout=5)
    except (httpx.ConnectError, httpx.TimeoutException):
        pytest.skip("실서버 미기동 — localhost:8001 연결 불가")


class TestTabPoolStatusLive:
    """[T5-http_live] 실서버에서 tab pool 상태가 정상 응답하는지 확인."""

    def test_system_status_returns_active_tabs(self):
        """GET /api/v1/system/status → active_tabs 필드 존재 확인."""
        _skip_if_down()
        resp = httpx.get(f"{BASE_URL}{STATUS_ENDPOINT}", timeout=10)
        assert resp.status_code == 200, f"status 오류: {resp.status_code}"
        data = resp.json()
        assert "active_tabs" in data, f"active_tabs 필드 없음: {data.keys()}"

    def test_active_tabs_non_negative(self):
        """GET /api/v1/system/status → active_tabs >= 0 (릭 없음 기본 확인)."""
        _skip_if_down()
        resp = httpx.get(f"{BASE_URL}{STATUS_ENDPOINT}", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        active_tabs = data.get("active_tabs", -1)
        assert active_tabs >= 0, f"active_tabs 음수 — tab pool 이상: {active_tabs}"

    def test_liveness_ok(self):
        """GET /api/v1/dev-runner/runners → 200 (asyncio.shield 변경 후 API 정상 기동 확인)."""
        _skip_if_down()
        resp = httpx.get(f"{BASE_URL}{LIVENESS_ENDPOINT}", timeout=10)
        assert resp.status_code == 200

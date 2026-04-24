"""
T4 E2E: anonymous 모드 복원 후 live API 계약 회귀 검증

anonymous monitoring_mode가 올바르게 복원됐는지 live API를 통해 확인한다:
1. 시스템 탭 상태가 비정상(초과)이 아님
2. 모니터링 이벤트 API에 fetch_method 필드가 포함됨
3. 스케줄 API에 monitoring_mode 필드 스키마가 있음 (개별 조회)

live API(localhost:8001) 미기동 시 skip (false-positive 방지).
/merge-test owner가 main runtime에서 실행한다.
"""
import pytest
import httpx

BASE = "http://localhost:8001"
pytestmark = pytest.mark.e2e


def _is_api_up() -> bool:
    try:
        r = httpx.get(f"{BASE}/api/v1/system/liveness", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(autouse=True)
def skip_if_api_down():
    if not _is_api_up():
        pytest.skip("live API(localhost:8001) 미기동 — skip (false-positive 방지)")


class TestAnonymousModeApiContract:
    """anonymous 모드 복원 후 API 계약이 유지됨을 확인."""

    def test_right_system_status_returns_tab_fields(self):
        """R: GET /api/v1/system/status → active_tabs/browser_contexts 필드 유지."""
        r = httpx.get(f"{BASE}/api/v1/system/status", timeout=10.0)
        assert r.status_code == 200, f"status {r.status_code}: {r.text[:200]}"
        data = r.json()
        for field in ("active_tabs", "browser_contexts"):
            assert field in data, f"'{field}' 필드 없음 — API 계약 회귀: {list(data.keys())}"

    def test_right_monitoring_events_include_fetch_method_field(self):
        """R: GET /api/v1/monitoring/events → fetch_method 필드가 응답에 포함됨."""
        r = httpx.get(
            f"{BASE}/api/v1/monitoring/events",
            params={"limit": 1},
            timeout=10.0,
            follow_redirects=True,
        )
        assert r.status_code == 200, f"status {r.status_code}: {r.text[:200]}"
        data = r.json()
        items = data.get("items", data if isinstance(data, list) else [])
        if not items:
            pytest.skip("모니터링 이벤트 없음 — 필드 유무 확인 불가, skip")
        first = items[0]
        assert "fetch_method" in first, (
            f"fetch_method 필드 없음 — anonymous/legacy 구분 불가: {list(first.keys())}"
        )

    def test_right_schedule_schema_has_monitoring_mode_field(self):
        """R: MonitorSchedule 스키마에 monitoring_mode 필드가 있음 (OpenAPI/schema 검증)."""
        r = httpx.get(f"{BASE}/openapi.json", timeout=10.0)
        assert r.status_code == 200
        schema = r.json()
        monitor_schedule = (
            schema.get("components", {})
            .get("schemas", {})
            .get("MonitorSchedule", {})
        )
        props = monitor_schedule.get("properties", {})
        assert "monitoring_mode" in props, (
            f"MonitorSchedule 스키마에 monitoring_mode 없음 — 이식 누락 가능성: {list(props.keys())}"
        )


class TestSystemTabBudgetHealth:
    """anonymous 모드 복원 후 탭 예산 상태가 정상임을 확인."""

    def test_right_system_liveness_responds_200(self):
        """R: /api/v1/system/liveness → 200 (worker 기동 중 + API 정상)."""
        r = httpx.get(f"{BASE}/api/v1/system/liveness", timeout=5.0)
        assert r.status_code == 200, f"liveness 실패: {r.status_code}"

    def test_right_active_tabs_not_overflowed(self):
        """R: active_tabs < 5 (TOTAL_MAX_TABS 초과 없음) — anonymous 모드 미복원 시 5/5 고착."""
        r = httpx.get(f"{BASE}/api/v1/system/status", timeout=10.0)
        assert r.status_code == 200
        data = r.json()
        active_tabs = data.get("active_tabs", 0)
        assert active_tabs < 5, (
            f"active_tabs={active_tabs} >= 5 — 탭 예산 초과 상태. "
            "anonymous 모드가 동작하지 않거나 다른 문제가 있을 수 있음."
        )

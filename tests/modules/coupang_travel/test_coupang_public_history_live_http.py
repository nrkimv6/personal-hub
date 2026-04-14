"""쿠팡 공개 전환 이력 T5 — 실서버(localhost:8001) HTTP 통합 테스트"""

import httpx
import pytest

pytestmark = pytest.mark.http_live

BASE_URL = "http://localhost:8001"
PUBLIC_HISTORY_URL = f"{BASE_URL}/api/v1/monitoring/events/coupang-public-history"


def _skip_if_down() -> None:
    try:
        httpx.get(BASE_URL, timeout=5)
    except httpx.ConnectError:
        pytest.fail("실서버 미기동 — localhost:8001 연결 불가")


def test_live_public_history_200_and_shape():
    """GET /coupang-public-history → 200 + 핵심 응답 구조 검증."""
    _skip_if_down()

    resp = httpx.get(PUBLIC_HISTORY_URL, timeout=30)
    assert resp.status_code == 200, f"예상 200, 실제 {resp.status_code}: {resp.text[:200]}"
    data = resp.json()

    assert "items" in data
    assert "summary" in data
    assert "slot_time_options" in data
    assert "total" in data
    assert isinstance(data["items"], list)
    assert isinstance(data["slot_time_options"], list)

    summary = data["summary"]
    assert "total" in summary
    assert "cancellation_count" in summary
    assert "sold_out_count" in summary
    assert isinstance(summary["total"], int)
    assert isinstance(summary["cancellation_count"], int)
    assert isinstance(summary["sold_out_count"], int)


def test_live_public_history_accepts_date_and_time_filters():
    """GET /coupang-public-history?schedule_date_from=...&slot_times=... → 200 + 필터 수용."""
    _skip_if_down()

    resp = httpx.get(
        PUBLIC_HISTORY_URL,
        params={
            "schedule_date_from": "2099-01-01",
            "schedule_date_to": "2099-12-31",
            "slot_times": "오전 10시",
            "page": 1,
            "page_size": 20,
        },
        timeout=30,
    )
    assert resp.status_code == 200, f"예상 200, 실제 {resp.status_code}: {resp.text[:200]}"
    data = resp.json()

    assert isinstance(data["items"], list)
    assert isinstance(data["slot_time_options"], list)
    assert data["summary"]["total"] >= 0

"""쿠팡 공개 전환 이력 T5 — 실서버(localhost:8001) HTTP 통합 테스트"""

import httpx
import pytest

pytestmark = pytest.mark.http_live

BASE_URL = "http://localhost:8000"
PUBLIC_HISTORY_URL = f"{BASE_URL}/api/v1/monitoring/events/coupang-public-history"


def _skip_if_down() -> None:
    try:
        httpx.get(BASE_URL, timeout=5)
    except httpx.ConnectError:
        pytest.skip("실서버 미기동 — localhost:8001 연결 불가")


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
    assert "closed_pair_count" in summary
    assert "open_pair_count" in summary
    assert "avg_closed_duration_seconds" in summary
    assert "cancellation_count" not in summary
    assert "total_sold" not in summary
    assert "remaining_open_count" not in summary
    assert isinstance(summary["total"], int)
    assert isinstance(summary["closed_pair_count"], int)
    assert isinstance(summary["open_pair_count"], int)
    if data["items"]:
        item = data["items"][0]
        assert isinstance(item["id"], str)
        assert "opened_at" in item
        assert "closed_at" in item
        assert item["status_label"] in {"다시 매진", "현재 열림"}
        if item["status_label"] == "다시 매진":
            assert item["closed_duration_seconds"] is not None
            assert item["open_duration_seconds"] is None
        else:
            assert item["closed_duration_seconds"] is None
            assert item["open_duration_seconds"] is not None


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
    assert isinstance(data["items"], list)

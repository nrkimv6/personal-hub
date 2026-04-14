"""취소표 통계 T5 — 실서버(localhost:8001) HTTP 통합 테스트

실제 서버가 기동된 상태에서만 의미 있다.
실서버 미기동 시 pytest.skip()으로 자동 건너뜀.

실행:
    pytest tests/modules/coupang_travel/test_cancellation_stats_live_http.py -m http_live -v
"""
import pytest
import httpx

pytestmark = pytest.mark.http_live

BASE_URL = "http://localhost:8001"
STATS_URL = f"{BASE_URL}/api/v1/monitoring/events/cancellation-stats"
BY_PRODUCT_URL = f"{BASE_URL}/api/v1/monitoring/events/cancellation-by-product"


def _skip_if_down() -> None:
    """실서버 미기동 시 테스트 skip."""
    try:
        httpx.get(BASE_URL, timeout=5)
    except httpx.ConnectError:
        pytest.fail("실서버 미기동 — localhost:8001 연결 불가")


def test_live_cancellation_stats_200():
    """GET /cancellation-stats → 200 + items 리스트 + summary 객체 존재 검증."""
    _skip_if_down()

    resp = httpx.get(STATS_URL, timeout=30)
    assert resp.status_code == 200, f"예상 200, 실제 {resp.status_code}: {resp.text[:200]}"
    data = resp.json()

    assert "items" in data, "응답에 items 키 없음"
    assert "summary" in data, "응답에 summary 키 없음"
    assert isinstance(data["items"], list), "items가 리스트가 아님"

    summary = data["summary"]
    assert "total" in summary
    assert "avg_per_day" in summary
    assert isinstance(summary["total"], int)
    assert isinstance(summary["avg_per_day"], float)


def test_live_cancellation_stats_hours_filter():
    """GET ...?hours=13,18 → 200 + items의 모든 hour가 13 또는 18인지 검증."""
    _skip_if_down()

    resp = httpx.get(STATS_URL, params={"hours": "13,18", "group_by": "hour"}, timeout=30)
    assert resp.status_code == 200, f"예상 200, 실제 {resp.status_code}"
    data = resp.json()

    assert "items" in data
    # 항목이 있으면 hours 필터가 적용됐는지 확인
    for item in data["items"]:
        if item.get("hour") is not None:
            assert item["hour"] in (13, 18), f"hour={item['hour']}는 필터 외 값"


def test_live_cancellation_stats_invalid_date():
    """GET ...?date_from=invalid → 200 (현재 패턴: invalid date 무시) + 정상 응답 구조."""
    _skip_if_down()

    resp = httpx.get(STATS_URL, params={"date_from": "invalid", "group_by": "hour"}, timeout=30)
    assert resp.status_code == 200, f"예상 200, 실제 {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert "items" in data
    assert "summary" in data


def test_live_cancellation_by_product_200():
    """GET /cancellation-by-product → 200 + items 리스트, 각 항목에 biz_item_name, total_count 필드 존재."""
    _skip_if_down()

    resp = httpx.get(BY_PRODUCT_URL, timeout=30)
    assert resp.status_code == 200, f"예상 200, 실제 {resp.status_code}"
    data = resp.json()

    assert "items" in data
    assert isinstance(data["items"], list)

    for item in data["items"]:
        assert "biz_item_name" in item, f"biz_item_name 누락: {item}"
        assert "total_count" in item, f"total_count 누락: {item}"
        assert "business_name" in item, f"business_name 누락: {item}"
        assert isinstance(item["total_count"], int)


def test_live_cancellation_by_product_empty():
    """GET /cancellation-by-product?date_from=2099-01-01&date_to=2099-12-31 → 200 + items=[]."""
    _skip_if_down()

    resp = httpx.get(
        BY_PRODUCT_URL,
        params={"date_from": "2099-01-01", "date_to": "2099-12-31"},
        timeout=30,
    )
    assert resp.status_code == 200, f"예상 200, 실제 {resp.status_code}"
    data = resp.json()
    assert data["items"] == [], f"미래 날짜 범위인데 items={data['items']}"

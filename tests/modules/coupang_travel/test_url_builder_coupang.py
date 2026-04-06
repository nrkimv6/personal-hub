"""
build_coupang_url 수정 회귀 테스트 (T3)
"""
from app.utils.url_builder import build_coupang_url, build_monitoring_url


def test_build_coupang_url():
    """수정된 시그니처: product_id만으로 URL 생성."""
    url = build_coupang_url("10000011218760")
    assert url == "https://trip.coupang.com/tp/products/10000011218760"


def test_build_coupang_url_with_date():
    """date 옵션 포함 URL 생성."""
    url = build_coupang_url("10000011218760", date="2026-04-10")
    assert url == "https://trip.coupang.com/tp/products/10000011218760?date=2026-04-10"


def test_build_monitoring_url_coupang():
    """build_monitoring_url이 item_biz_item_id 값을 URL에 반영하는지 확인."""
    schedule_context = {
        "service_type": "coupang",
        "item_biz_item_id": "99887766",
        "date": "2026-04-10",
    }
    url = build_monitoring_url(schedule_context)
    assert "99887766" in url
    assert "trip.coupang.com" in url

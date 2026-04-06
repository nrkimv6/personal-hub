"""
URL 파서 테스트 (RIGHT-BICEP: R, B, E)
"""
import pytest
from app.modules.coupang_travel.utils.url_parser import parse_coupang_url


def test_parse_coupang_url_right():
    """R: 정상 URL (tp/products 경로)"""
    result = parse_coupang_url("https://trip.coupang.com/tp/products/10000011218760")
    assert result == {"product_id": "10000011218760"}


def test_parse_coupang_url_without_tp():
    """R: tp 없는 URL"""
    result = parse_coupang_url("https://trip.coupang.com/products/10000011218760")
    assert result == {"product_id": "10000011218760"}


def test_parse_coupang_url_with_query():
    """B: 쿼리스트링 포함 URL"""
    result = parse_coupang_url("https://trip.coupang.com/tp/products/123?date=2026-04-19")
    assert result == {"product_id": "123"}


def test_parse_coupang_url_trailing_slash():
    """B: 끝 슬래시 포함 URL"""
    result = parse_coupang_url("https://trip.coupang.com/tp/products/123/")
    assert result == {"product_id": "123"}


def test_parse_coupang_url_invalid():
    """E: 쿠팡 여행 URL이 아닌 경우"""
    with pytest.raises(ValueError):
        parse_coupang_url("https://coupang.com/vp/products/123")


def test_parse_coupang_url_empty():
    """E: 빈 URL"""
    with pytest.raises(ValueError):
        parse_coupang_url("")

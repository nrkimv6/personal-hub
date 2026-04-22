"""
site_monitor URL 파싱 방어 TC

parse_naver_booking_url() 직접 + perform_task_with_fetch 비숫자 category 조기 실패 검증.

- R: 유효 숫자 category URL → is_valid=True, category 숫자
- E: 한글 category URL → site_monitor가 status='error', reason에 '합성 결함' 포함
- B: startDateTime 없는 URL → start_date=None → extract_date_only=None
- B2: 완전히 다른 URL 포맷 → is_valid=False
"""
import pytest
import sys
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestParseNaverBookingUrl:
    """parse_naver_booking_url 순수함수 직접 테스트"""

    def test_parse_right_numeric_category_passes(self):
        """R: 정상 숫자 category URL → is_valid=True, category='13'"""
        from app.modules.naver_booking.utils.parsers import parse_naver_booking_url

        url = "https://booking.naver.com/booking/13/bizes/1630978/items/6309731?startDateTime=2026-04-26T00%3A00%3A00%2B09%3A00"
        result = parse_naver_booking_url(url)

        assert result.is_valid is True
        assert result.category == "13"
        assert result.category.isdigit()
        assert result.business_id == "1630978"
        assert result.item_id == "6309731"
        assert result.start_date is not None

    def test_parse_error_korean_category_category_is_not_digit(self):
        """E(parser레벨): 한글 category URL → is_valid=True이지만 category가 비숫자 → site_monitor에서 걸림"""
        from app.modules.naver_booking.utils.parsers import parse_naver_booking_url

        url = "https://booking.naver.com/booking/올리브영N성수/bizes/13/items/6309731?startDateTime=2026-04-22T00%3A00%3A00%2B09%3A00"
        result = parse_naver_booking_url(url)

        assert not result.category.isdigit(), (
            f"category가 숫자여서는 안 됨 (버그 재발): {result.category!r}"
        )

    def test_parse_boundary_missing_startDateTime_start_date_is_none(self):
        """B: startDateTime 쿼리 없는 URL → start_date=None, extract_date_only=None"""
        from app.modules.naver_booking.utils.parsers import parse_naver_booking_url
        from app.utils.parsers import extract_date_only

        url = "https://booking.naver.com/booking/13/bizes/1630978/items/6309731"
        result = parse_naver_booking_url(url)

        assert result.is_valid is True
        assert result.start_date is None
        assert extract_date_only(result.start_date) is None

    def test_parse_boundary_invalid_url_format_returns_invalid(self):
        """B2: 전혀 다른 URL → is_valid=False"""
        from app.modules.naver_booking.utils.parsers import parse_naver_booking_url

        url = "https://example.com/not-naver-booking"
        result = parse_naver_booking_url(url)

        assert result.is_valid is False


class TestSiteMonitorKoreanCategoryError:
    """perform_task_with_fetch — 한글 category URL 조기 실패 검증"""

    def test_perform_task_with_fetch_korean_category_returns_error_status(self):
        """E: 한글 category URL → status='error', reason에 '합성 결함' 포함"""
        from app.modules.naver_booking.services.site_monitor import NaverSiteMonitor, FetchResult

        monitor = NaverSiteMonitor(notification_service=None, browser_service=None)
        url = "https://booking.naver.com/booking/올리브영N성수/bizes/13/items/6309731?startDateTime=2026-04-22T00%3A00%3A00%2B09%3A00"
        page_mock = MagicMock()

        result = asyncio.run(
            monitor.perform_task_with_fetch(
                page=page_mock,
                url=url,
                tag="test/6309731",
                current_hash=0,
                current_data=[],
            )
        )

        assert isinstance(result, FetchResult)
        assert result.status == "error"
        assert result.reason is not None
        assert "합성 결함" in result.reason

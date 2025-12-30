"""
app/utils/parsers.py 테스트

공통 파서 유틸리티 함수들의 순수 함수 테스트
"""
import pytest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from app.utils.parsers import (
    extract_date_only,
    extract_date_from_url,
    calculate_interval
)


class TestExtractDateOnly:
    """날짜만 추출 테스트"""

    # Right - 정상 케이스
    def test_right_extract_from_iso_datetime(self):
        """ISO datetime에서 날짜 추출"""
        result = extract_date_only("2025-12-15T00:00:00+09:00")
        assert result == "2025-12-15"

    def test_right_extract_from_simple_date(self):
        """단순 날짜 문자열"""
        result = extract_date_only("2025-12-15")
        assert result == "2025-12-15"

    def test_right_extract_from_datetime_with_time(self):
        """시간이 포함된 datetime"""
        result = extract_date_only("2025-12-15T14:30:00")
        assert result == "2025-12-15"

    # Boundary - 경계값
    def test_boundary_none_input(self):
        """None 입력"""
        result = extract_date_only(None)
        assert result is None

    def test_boundary_empty_string(self):
        """빈 문자열"""
        result = extract_date_only("")
        assert result is None

    # Error - 에러 케이스
    def test_error_invalid_format(self):
        """잘못된 형식"""
        result = extract_date_only("15-12-2025")
        assert result is None

    def test_error_partial_date(self):
        """불완전한 날짜"""
        result = extract_date_only("2025-12")
        assert result is None


class TestExtractDateFromUrl:
    """URL에서 날짜 추출 테스트"""

    # Right - 정상 케이스
    def test_right_extract_start_date_time(self):
        """startDateTime 파라미터에서 추출"""
        # URL에서 +는 공백으로 디코딩됨 (URL 인코딩 규칙)
        url = "https://booking.naver.com/booking/5/bizes/12345/items/67890?startDateTime=2025-12-15T00:00:00+09:00"
        result = extract_date_from_url(url)
        # +가 공백으로 변환됨
        assert result == "2025-12-15T00:00:00 09:00"

    def test_right_extract_start_date(self):
        """startDate 파라미터에서 추출"""
        url = "https://booking.naver.com/booking/5/bizes/12345/items/67890?startDate=2025-12-15"
        result = extract_date_from_url(url)
        assert result == "2025-12-15"

    def test_right_start_date_time_priority(self):
        """startDateTime이 startDate보다 우선"""
        url = "https://example.com?startDateTime=2025-12-15T10:00:00&startDate=2025-12-20"
        result = extract_date_from_url(url)
        assert result == "2025-12-15T10:00:00"

    # Boundary - 경계값
    def test_boundary_no_date_params(self):
        """날짜 파라미터 없음"""
        url = "https://booking.naver.com/booking/5/bizes/12345/items/67890"
        result = extract_date_from_url(url)
        assert result is None

    def test_boundary_empty_url(self):
        """빈 URL"""
        result = extract_date_from_url("")
        assert result is None

    def test_boundary_url_with_other_params(self):
        """다른 파라미터만 있는 URL"""
        url = "https://example.com?foo=bar&baz=qux"
        result = extract_date_from_url(url)
        assert result is None


class TestCalculateInterval:
    """모니터링 간격 계산 테스트"""

    # Right - 정상 케이스
    @patch('app.utils.parsers.datetime')
    def test_right_past_date_short_interval(self, mock_datetime):
        """과거 날짜 - 짧은 간격 (2-7초)"""
        # now를 고정
        mock_now = datetime(2025, 12, 30, 12, 0, 0, tzinfo=timezone(timedelta(hours=9)))
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        result = calculate_interval("2025-12-29T00:00:00+09:00")
        # random.uniform(2, 7) 범위 확인
        assert result is not None
        assert 2 <= result <= 7

    @patch('app.utils.parsers.datetime')
    def test_right_tomorrow_medium_interval(self, mock_datetime):
        """내일 - 중간 간격 (3-10초)"""
        mock_now = datetime(2025, 12, 30, 12, 0, 0, tzinfo=timezone(timedelta(hours=9)))
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        result = calculate_interval("2025-12-31T00:00:00+09:00")
        assert result is not None
        assert 3 <= result <= 10

    @patch('app.utils.parsers.datetime')
    def test_right_week_later_long_interval(self, mock_datetime):
        """1주일 이상 후 - 긴 간격 (200-300초)"""
        mock_now = datetime(2025, 12, 30, 12, 0, 0, tzinfo=timezone(timedelta(hours=9)))
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        result = calculate_interval("2026-01-10T00:00:00+09:00")
        assert result is not None
        assert 200 <= result <= 300

    @patch('app.utils.parsers.datetime')
    def test_right_few_days_later_medium_long_interval(self, mock_datetime):
        """2-7일 후 - 중장간 간격 (20-50초)"""
        mock_now = datetime(2025, 12, 30, 12, 0, 0, tzinfo=timezone(timedelta(hours=9)))
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        result = calculate_interval("2026-01-02T00:00:00+09:00")
        assert result is not None
        assert 20 <= result <= 50

    # Boundary - 경계값
    def test_boundary_none_input(self):
        """None 입력"""
        result = calculate_interval(None)
        assert result is None

    def test_boundary_date_only_format(self):
        """날짜만 있는 형식 (T 없음)"""
        result = calculate_interval("2025-12-30")
        # T가 없으면 T00:00:00+0900을 추가하여 파싱
        assert result is not None

    # Error - 에러 케이스
    def test_error_invalid_format_returns_random(self):
        """잘못된 형식 - 랜덤 반환"""
        result = calculate_interval("invalid-date")
        # 파싱 실패 시 random.uniform(2, 7) 반환
        assert result is not None
        assert 2 <= result <= 7

    def test_right_space_separated_timezone(self):
        """공백으로 구분된 시간대"""
        result = calculate_interval("2025-12-30T00:00:00 0900")
        assert result is not None

    def test_right_0000_format_timezone(self):
        """0000 형식 시간대"""
        result = calculate_interval("2025-12-30T00:00:00+0000")
        assert result is not None

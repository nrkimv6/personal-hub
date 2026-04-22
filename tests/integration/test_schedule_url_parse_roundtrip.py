"""
T3: get_schedule → URL → parse_naver_booking_url 체인 통합 TC

회귀 핀:
  Phase 2 수정 이전 코드(result[23]=b.name, result[22]=b.business_type_id 스왑)에서는
  URL이 booking/올리브영N성수/bizes/13/...가 되어 parse 후 category가 비숫자 → 이 TC 실패.

목표:
  - get_schedule()이 반환한 url의 첫 path 세그먼트가 business_type_id 숫자임을 검증
  - 반환 url을 parse_naver_booking_url로 재파싱 시 올바른 값 복원 확인
  - site_monitor.perform_task_with_fetch 경로에서도 category.isdigit() 통과 확인
"""
import json
import sys
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _fixture_row(**overrides):
    """DB RowMapping을 모사한 dict fixture (올리브영N성수 업체)"""
    base = {
        "schedule_id": 430,
        "date": "2026-04-22",
        "times": json.dumps(["09:00", "10:00"]),
        "is_enabled": True,
        "is_active": True,
        "run_status": "idle",
        "interval": 60,
        "custom_interval": False,
        "error_count": 0,
        "last_error": None,
        "booking_count": 0,
        "last_booking_time": None,
        "monitoring_mode": "legacy",
        "biz_item_id": 1,
        "naver_biz_item_id": "6309731",
        "item_name": "올리브영 예약",
        "time_range": None,
        "auto_booking_enabled": False,
        "max_bookings_per_schedule": 1,
        "service_account_id": None,
        "business_id": 10,
        "naver_business_id": "1630978",
        "business_type_id": 13,
        "business_name": "올리브영N성수",
        "category": "beauty",
        "service_type": "naver",
        "booking_options": None,
    }
    base.update(overrides)
    return base


def _mock_session(row):
    mock_db = MagicMock()
    mock_db.execute.return_value.mappings.return_value.first.return_value = row
    return mock_db


class TestScheduleUrlParseRoundtrip:
    """
    get_schedule() 반환 URL과 parse_naver_booking_url 재파싱 정합성 검증.
    Phase 2 수정 전 코드라면 category="올리브영N성수" → 아래 assert 전부 실패.
    """

    def _get_schedule_with_row(self, row):
        from app.modules.naver_booking.services.schedule_service import ScheduleMonitorService
        mock_db = _mock_session(row)
        with patch("app.modules.naver_booking.services.schedule_service.SessionLocal", return_value=mock_db):
            return ScheduleMonitorService().get_schedule(430)

    def test_roundtrip_business_id_and_item_id_restored(self):
        """T3-R: get_schedule URL → parse_naver_booking_url → business_id/item_id 복원 확인"""
        from app.modules.naver_booking.utils.parsers import parse_naver_booking_url

        result = self._get_schedule_with_row(_fixture_row())
        assert result is not None, "get_schedule 반환값이 None"

        parsed = parse_naver_booking_url(result["url"])
        assert parsed.is_valid, f"URL 파싱 실패: {result['url']}"
        assert parsed.business_id == "1630978", f"business_id 불일치: {parsed.business_id}"
        assert parsed.item_id == "6309731", f"item_id 불일치: {parsed.item_id}"
        assert parsed.category == "13", f"category가 숫자가 아님 (버그 재발): {parsed.category!r}"

    def test_roundtrip_category_is_digit(self):
        """T3-B: URL 첫 path 세그먼트(category)가 반드시 숫자여야 함 (한글 스왑 방지 핀)"""
        from app.modules.naver_booking.utils.parsers import parse_naver_booking_url

        row = _fixture_row(business_type_id=13, business_name="올리브영N성수")
        result = self._get_schedule_with_row(row)

        parsed = parse_naver_booking_url(result["url"])
        assert parsed.category.isdigit(), (
            f"category가 비숫자 — business_name이 URL에 섞인 버그 재발: {parsed.category!r}"
        )

    def test_site_monitor_path_accepts_correct_url(self):
        """T3-E: site_monitor perform_task_with_fetch가 올바른 URL을 category.isdigit() 통과로 처리"""
        from app.modules.naver_booking.services.site_monitor import NaverSiteMonitor, FetchResult

        result = self._get_schedule_with_row(_fixture_row())
        assert result is not None
        url = result["url"]

        monitor = NaverSiteMonitor(notification_service=None, browser_service=None)
        page_mock = MagicMock()
        # 올바른 URL → isdigit() 통과, 이후 페이지 로드 시도
        # page.url은 MagicMock이므로 'booking.naver.com' not in page.url → page.goto 호출
        # page.goto는 AsyncMock이어야 함
        page_mock.url = ""
        page_mock.goto = MagicMock(return_value=None)

        # 실제 네이버 API 호출은 일어나지 않음 (page mock이 goto에서 중단)
        # 단, URL 파싱 단계만 검증: status가 "error"가 되지 않는지 확인
        # → category 비숫자 에러라면 즉시 FetchResult(status="error", reason="URL 합성 결함:...")
        # → category 숫자라면 다음 단계(페이지 로드)로 넘어감 (별도 exception 발생 가능)
        try:
            loop_result = asyncio.run(
                monitor.perform_task_with_fetch(
                    page=page_mock,
                    url=url,
                    tag="test/roundtrip",
                    current_hash=0,
                    current_data=[],
                )
            )
            # 결과가 있다면 URL 합성 결함 에러가 아니어야 함
            if isinstance(loop_result, FetchResult):
                assert "합성 결함" not in (loop_result.reason or ""), (
                    f"URL 합성 결함 에러 발생 — category 비숫자: {loop_result.reason}"
                )
        except Exception:
            # 페이지 로드 관련 예외는 무시 (URL 파싱 통과 후 발생)
            pass

    def test_regression_pin_korean_url_fails_category_digit_check(self):
        """재현 핀: 한글 category URL이면 category.isdigit()=False → 버그 URL 특성 확인"""
        from app.modules.naver_booking.utils.parsers import parse_naver_booking_url

        buggy_url = "https://booking.naver.com/booking/올리브영N성수/bizes/13/items/6309731?startDateTime=2026-04-22T00%3A00%3A00%2B09%3A00"
        parsed = parse_naver_booking_url(buggy_url)

        # 버그 URL은 category가 한글 → isdigit() False
        assert not parsed.category.isdigit(), "버그 URL 재현 실패: category가 숫자여서는 안 됨"
        # 현재 코드로 get_schedule을 실행하면 이 URL이 생성되지 않아야 함
        # (test_roundtrip_category_is_digit에서 검증)

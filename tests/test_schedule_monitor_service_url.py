"""
ScheduleMonitorService.get_schedule URL 합성 검증 TC

RIGHT-BICEP 원칙:
- R(Right): 올바른 입력 → URL 첫 path 세그먼트가 business_type_id 숫자
- B(Boundary): 한글 업체명 포함 / NULL business_type_id 폴백
- E(Error): 존재하지 않는 schedule_id → None
- C(Cross-check): 반환 dict와 URL 세그먼트 정합성

버그: business_type_id=result[23](b.name)과 business_id=result[22](b.business_type_id)가
     스왑되어 booking/올리브영N성수/bizes/13/... 형태의 URL이 생성됐었음.
     .mappings().first() + 이름 기반 접근으로 수정됨.
"""
import pytest
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _make_row(**overrides):
    """테스트용 DB RowMapping dict 생성"""
    defaults = {
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
    defaults.update(overrides)
    return defaults


def _mock_session(row):
    """SessionLocal() 반환값 mock — execute().mappings().first() 체인"""
    mock_db = MagicMock()
    mock_db.execute.return_value.mappings.return_value.first.return_value = row
    return mock_db


class TestGetScheduleUrlSynthesis:

    def test_get_schedule_right_returns_numeric_first_segment_url(self):
        """R: business_type_id=13, naver_business_id='1630978' 행 → URL 첫 path 세그먼트가 '13'"""
        from app.modules.naver_booking.services.schedule_service import ScheduleMonitorService

        row = _make_row(business_type_id=13, naver_business_id="1630978", naver_biz_item_id="6309731")
        mock_db = _mock_session(row)

        with patch("app.modules.naver_booking.services.schedule_service.SessionLocal", return_value=mock_db):
            result = ScheduleMonitorService().get_schedule(430)

        assert result is not None
        assert "/booking/13/bizes/1630978/items/6309731" in result["url"]

    def test_get_schedule_boundary_business_name_with_korean_not_in_url(self):
        """B: business_name이 한글 '올리브영N성수'이어도 URL 첫 path 세그먼트는 숫자여야 함"""
        from app.modules.naver_booking.services.schedule_service import ScheduleMonitorService

        row = _make_row(business_type_id=13, naver_business_id="1630978", business_name="올리브영N성수")
        mock_db = _mock_session(row)

        with patch("app.modules.naver_booking.services.schedule_service.SessionLocal", return_value=mock_db):
            result = ScheduleMonitorService().get_schedule(430)

        assert result is not None
        assert "올리브영N성수" not in result["url"]
        # URL path에서 /booking/{seg}/ 세그먼트 추출
        path_part = result["url"].split("?")[0]
        segments = path_part.split("/")
        booking_idx = segments.index("booking")
        first_seg = segments[booking_idx + 1]
        assert first_seg.isdigit(), f"URL 첫 path 세그먼트가 비숫자: {first_seg!r}"

    def test_get_schedule_boundary_business_type_id_null_fallback(self):
        """B: business_type_id=None → 폴백 13으로 URL이 /booking/13/bizes/...가 되어야 함"""
        from app.modules.naver_booking.services.schedule_service import ScheduleMonitorService

        row = _make_row(business_type_id=None, naver_business_id="1630978")
        mock_db = _mock_session(row)

        with patch("app.modules.naver_booking.services.schedule_service.SessionLocal", return_value=mock_db):
            result = ScheduleMonitorService().get_schedule(430)

        assert result is not None
        assert "/booking/13/bizes/" in result["url"], f"폴백 미적용: {result['url']}"

    def test_get_schedule_error_missing_schedule_returns_none(self):
        """E: 존재하지 않는 schedule_id → None 반환 (DB row 없음)"""
        from app.modules.naver_booking.services.schedule_service import ScheduleMonitorService

        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.first.return_value = None

        with patch("app.modules.naver_booking.services.schedule_service.SessionLocal", return_value=mock_db):
            result = ScheduleMonitorService().get_schedule(99999)

        assert result is None

    def test_get_schedule_cross_url_and_dict_consistency(self):
        """C: 반환 dict의 business_type_id/naver_business_id/naver_biz_item_id가 URL 세그먼트와 일치"""
        from app.modules.naver_booking.services.schedule_service import ScheduleMonitorService

        row = _make_row(business_type_id=13, naver_business_id="1630978", naver_biz_item_id="6309731")
        mock_db = _mock_session(row)

        with patch("app.modules.naver_booking.services.schedule_service.SessionLocal", return_value=mock_db):
            result = ScheduleMonitorService().get_schedule(430)

        assert result is not None
        expected_path = f"/booking/{result['business_type_id']}/bizes/{result['naver_business_id']}/items/{result['naver_biz_item_id']}"
        assert expected_path in result["url"], (
            f"dict 필드와 URL 불일치: dict={result['business_type_id']}/{result['naver_business_id']}/{result['naver_biz_item_id']}, url={result['url']}"
        )

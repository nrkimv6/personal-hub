"""
슬롯 조회 API 테스트 (REQ-MON-012)

RIGHT-BICEP 원칙 적용:
- Right: 결과가 올바른가?
- Boundary: 경계값 테스트
- Inverse: 역관계 검증
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트

CORRECT 조건 적용:
- Conformance: 형식 준수
- Ordering: 순서 보장
- Range: 범위 검증
- Reference: 참조 검증
- Existence: 존재 여부
- Cardinality: 개수 검증
- Time: 시간 관련 테스트

테스트 대상:
- GET /api/v1/slots/check
- URL 파싱
- 슬롯 조회 응답
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from app.main import app
from app.routes.slot_check import parse_naver_url, build_response, DAY_OF_WEEK_KR
from app.services.naver_graphql_client import (
    BusinessInfo, BizItemInfo, ScheduleInfo, ScheduleSlot
)


# ============================================================
# 테스트 클라이언트
# ============================================================

client = TestClient(app)


# ============================================================
# Mock 데이터
# ============================================================

def create_mock_business_info(business_id: str = "1269828"):
    """테스트용 업체 정보 생성"""
    return BusinessInfo(
        business_id=business_id,
        name="테스트 업체",
        business_type_id=13,
        place_id="12345",
        service_name="테스트 서비스"
    )


def create_mock_biz_item_info(biz_item_id: str = "6309738"):
    """테스트용 상품 정보 생성"""
    return BizItemInfo(
        biz_item_id=biz_item_id,
        name="테스트 상품",
        description="테스트 설명",
        biz_item_type="NORMAL"
    )


def create_mock_schedule_slot(
    date: str = "2025-12-20",
    time: str = "10:00",
    unit_stock: int = 10,
    unit_booking_count: int = 5,
    is_sale_day: bool = True,
    is_unit_business_day: bool = True,
    is_unit_sale_day: bool = True
) -> ScheduleSlot:
    """테스트용 슬롯 생성"""
    return ScheduleSlot(
        slot_id=f"slot_{date}_{time}",
        start_time=f"{date} {time}:00",
        date=date,
        time=time,
        is_business_day=True,
        is_sale_day=is_sale_day,
        is_unit_business_day=is_unit_business_day,
        is_unit_sale_day=is_unit_sale_day,
        stock=unit_stock - unit_booking_count if is_sale_day else 0,
        unit_stock=unit_stock,
        unit_booking_count=unit_booking_count,
        duration=30,
        min_booking_count=1,
        max_booking_count=10,
        prices=[],
        raw_data={}
    )


def create_mock_schedule_info(
    business_id: str = "1269828",
    biz_item_id: str = "6309738",
    dates: list = None,
    slots_per_day: int = 3
) -> ScheduleInfo:
    """테스트용 스케줄 정보 생성"""
    if dates is None:
        dates = ["2025-12-20", "2025-12-21"]

    slots = []
    slots_by_date = {}
    available_dates = []

    times = ["10:00", "10:30", "11:00"][:slots_per_day]

    for date in dates:
        slots_by_date[date] = []
        has_available = False

        for i, time in enumerate(times):
            # 첫 번째 슬롯은 예약 가능, 나머지는 만석
            unit_stock = 10
            unit_booking_count = 5 if i == 0 else 10
            is_sale_day = True

            slot = create_mock_schedule_slot(
                date=date,
                time=time,
                unit_stock=unit_stock,
                unit_booking_count=unit_booking_count,
                is_sale_day=is_sale_day
            )
            slots.append(slot)
            slots_by_date[date].append(slot)

            if unit_stock - unit_booking_count > 0 and is_sale_day:
                has_available = True

        if has_available:
            available_dates.append(date)

    return ScheduleInfo(
        business_id=business_id,
        biz_item_id=biz_item_id,
        available_dates=available_dates,
        slots=slots,
        slots_by_date=slots_by_date
    )


# ============================================================
# RIGHT-BICEP 테스트
# ============================================================

class TestRight:
    """Right: 결과가 올바른가?"""

    def test_parse_url_valid_desktop(self):
        """데스크톱 URL 파싱"""
        url = "https://booking.naver.com/booking/13/bizes/1269828/items/6309738"
        business_id, biz_item_id = parse_naver_url(url)

        assert business_id == "1269828"
        assert biz_item_id == "6309738"

    def test_parse_url_valid_mobile(self):
        """모바일 URL 파싱"""
        url = "https://m.booking.naver.com/booking/13/bizes/1551499/items/7277503"
        business_id, biz_item_id = parse_naver_url(url)

        assert business_id == "1551499"
        assert biz_item_id == "7277503"

    def test_parse_url_with_query_params(self):
        """쿼리 파라미터가 있는 URL 파싱"""
        url = "https://booking.naver.com/booking/13/bizes/1269828/items/6309738?startDateTime=2025-12-20"
        business_id, biz_item_id = parse_naver_url(url)

        assert business_id == "1269828"
        assert biz_item_id == "6309738"

    def test_build_response_structure(self):
        """응답 구조 검증"""
        business = create_mock_business_info()
        biz_item = create_mock_biz_item_info()
        schedule = create_mock_schedule_info()

        response = build_response(business, biz_item, schedule)

        # 필수 필드 확인
        assert response.business.business_id == "1269828"
        assert response.business.name == "테스트 업체"
        assert response.biz_item.biz_item_id == "6309738"
        assert response.biz_item.name == "테스트 상품"
        assert response.summary.total_slots == 6  # 2일 x 3슬롯
        assert len(response.slots_by_date) == 2

    def test_build_response_slot_calculation(self):
        """슬롯 계산 검증 (정원/예약됨/남음)"""
        business = create_mock_business_info()
        biz_item = create_mock_biz_item_info()
        schedule = create_mock_schedule_info(dates=["2025-12-20"], slots_per_day=1)

        response = build_response(business, biz_item, schedule)

        date_slots = response.slots_by_date[0]
        slot = date_slots.slots[0]

        assert slot.capacity == 10  # unit_stock
        assert slot.booked == 5     # unit_booking_count
        assert slot.remaining == 5  # capacity - booked
        assert slot.is_available is True

    @patch('app.modules.naver_booking.routes.slot_check.NaverGraphQLClient')
    def test_check_slots_by_url(self, mock_client_class):
        """URL로 슬롯 조회"""
        # Mock 설정
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.fetch_business_info.return_value = create_mock_business_info()
        mock_client.fetch_biz_item.return_value = create_mock_biz_item_info()
        mock_client.fetch_schedule.return_value = create_mock_schedule_info()

        response = client.get(
            "/api/v1/slots/check",
            params={"url": "https://booking.naver.com/booking/13/bizes/1269828/items/6309738"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["business"]["business_id"] == "1269828"
        assert data["biz_item"]["biz_item_id"] == "6309738"

    @patch('app.modules.naver_booking.routes.slot_check.NaverGraphQLClient')
    def test_check_slots_by_ids(self, mock_client_class):
        """ID로 슬롯 조회"""
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.fetch_business_info.return_value = create_mock_business_info()
        mock_client.fetch_biz_item.return_value = create_mock_biz_item_info()
        mock_client.fetch_schedule.return_value = create_mock_schedule_info()

        response = client.get(
            "/api/v1/slots/check",
            params={"business_id": "1269828", "biz_item_id": "6309738"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["business"]["business_id"] == "1269828"


class TestBoundary:
    """Boundary: 경계값 테스트"""

    def test_days_ahead_min(self):
        """days_ahead 최소값 (1)"""
        with patch('app.modules.naver_booking.routes.slot_check.NaverGraphQLClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.fetch_business_info.return_value = create_mock_business_info()
            mock_client.fetch_biz_item.return_value = create_mock_biz_item_info()
            mock_client.fetch_schedule.return_value = create_mock_schedule_info()

            response = client.get(
                "/api/v1/slots/check",
                params={"business_id": "1269828", "biz_item_id": "6309738", "days_ahead": 1}
            )

            assert response.status_code == 200
            # fetch_schedule이 days_ahead=1로 호출되었는지 확인
            mock_client.fetch_schedule.assert_called_once()
            call_kwargs = mock_client.fetch_schedule.call_args.kwargs
            assert call_kwargs["days_ahead"] == 1

    def test_days_ahead_max(self):
        """days_ahead 최대값 (35)"""
        with patch('app.modules.naver_booking.routes.slot_check.NaverGraphQLClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.fetch_business_info.return_value = create_mock_business_info()
            mock_client.fetch_biz_item.return_value = create_mock_biz_item_info()
            mock_client.fetch_schedule.return_value = create_mock_schedule_info()

            response = client.get(
                "/api/v1/slots/check",
                params={"business_id": "1269828", "biz_item_id": "6309738", "days_ahead": 35}
            )

            assert response.status_code == 200

    def test_days_ahead_over_max(self):
        """days_ahead 최대값 초과 (36)"""
        response = client.get(
            "/api/v1/slots/check",
            params={"business_id": "1269828", "biz_item_id": "6309738", "days_ahead": 36}
        )

        assert response.status_code == 422  # Validation Error

    def test_days_ahead_zero(self):
        """days_ahead 0 (최소값 미만)"""
        response = client.get(
            "/api/v1/slots/check",
            params={"business_id": "1269828", "biz_item_id": "6309738", "days_ahead": 0}
        )

        assert response.status_code == 422  # Validation Error


class TestError:
    """Error: 에러 조건 테스트"""

    def test_missing_params(self):
        """필수 파라미터 누락"""
        response = client.get("/api/v1/slots/check")

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["code"] == "MISSING_PARAMS"

    def test_invalid_url_format(self):
        """잘못된 URL 형식"""
        response = client.get(
            "/api/v1/slots/check",
            params={"url": "https://naver.com/invalid/url"}
        )

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["code"] == "INVALID_URL"

    @patch('app.modules.naver_booking.routes.slot_check.NaverGraphQLClient')
    def test_business_not_found(self, mock_client_class):
        """업체를 찾을 수 없음"""
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.fetch_business_info.return_value = None

        response = client.get(
            "/api/v1/slots/check",
            params={"business_id": "9999999", "biz_item_id": "1234567"}
        )

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["code"] == "BUSINESS_NOT_FOUND"

    @patch('app.modules.naver_booking.routes.slot_check.NaverGraphQLClient')
    def test_item_not_found(self, mock_client_class):
        """상품을 찾을 수 없음"""
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.fetch_business_info.return_value = create_mock_business_info()
        mock_client.fetch_biz_item.return_value = None

        response = client.get(
            "/api/v1/slots/check",
            params={"business_id": "1269828", "biz_item_id": "9999999"}
        )

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["code"] == "ITEM_NOT_FOUND"

    @patch('app.modules.naver_booking.routes.slot_check.NaverGraphQLClient')
    def test_graphql_error(self, mock_client_class):
        """GraphQL API 실패"""
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.fetch_business_info.return_value = create_mock_business_info()
        mock_client.fetch_biz_item.return_value = create_mock_biz_item_info()
        mock_client.fetch_schedule.return_value = None

        response = client.get(
            "/api/v1/slots/check",
            params={"business_id": "1269828", "biz_item_id": "6309738"}
        )

        assert response.status_code == 500
        data = response.json()
        assert data["detail"]["code"] == "GRAPHQL_ERROR"


class TestInverse:
    """Inverse: 역관계 검증"""

    def test_url_parsing_roundtrip(self):
        """URL 파싱 후 원래 ID 복원"""
        original_business_id = "1269828"
        original_biz_item_id = "6309738"
        url = f"https://booking.naver.com/booking/13/bizes/{original_business_id}/items/{original_biz_item_id}"

        business_id, biz_item_id = parse_naver_url(url)

        assert business_id == original_business_id
        assert biz_item_id == original_biz_item_id


class TestCrossCheck:
    """Cross-check: 교차 검증"""

    def test_available_slots_count_matches(self):
        """예약 가능 슬롯 수 일치 확인"""
        business = create_mock_business_info()
        biz_item = create_mock_biz_item_info()

        # 2일 x 3슬롯, 각 날짜에 1개씩 예약 가능
        schedule = create_mock_schedule_info(dates=["2025-12-20", "2025-12-21"], slots_per_day=3)

        response = build_response(business, biz_item, schedule)

        # summary.total_available_slots와 실제 개수 비교
        actual_count = sum(
            1 for date_slots in response.slots_by_date
            for slot in date_slots.slots
            if slot.is_available
        )

        assert response.summary.total_available_slots == actual_count
        assert response.summary.total_available_slots == 2  # 각 날짜에 1개


# ============================================================
# CORRECT 테스트
# ============================================================

class TestConformance:
    """Conformance: 형식 준수"""

    def test_date_format(self):
        """날짜 형식 (YYYY-MM-DD)"""
        business = create_mock_business_info()
        biz_item = create_mock_biz_item_info()
        schedule = create_mock_schedule_info(dates=["2025-12-20"])

        response = build_response(business, biz_item, schedule)

        date_str = response.slots_by_date[0].date
        # YYYY-MM-DD 형식 검증
        datetime.strptime(date_str, "%Y-%m-%d")

    def test_time_format(self):
        """시간 형식 (HH:MM)"""
        business = create_mock_business_info()
        biz_item = create_mock_biz_item_info()
        schedule = create_mock_schedule_info(dates=["2025-12-20"], slots_per_day=1)

        response = build_response(business, biz_item, schedule)

        time_str = response.slots_by_date[0].slots[0].time
        # HH:MM 형식 검증
        datetime.strptime(time_str, "%H:%M")

    def test_day_of_week_korean(self):
        """요일 한글 형식"""
        business = create_mock_business_info()
        biz_item = create_mock_biz_item_info()
        schedule = create_mock_schedule_info(dates=["2025-12-20"])  # 토요일

        response = build_response(business, biz_item, schedule)

        day_of_week = response.slots_by_date[0].day_of_week
        assert day_of_week in DAY_OF_WEEK_KR
        assert day_of_week == "토"  # 2025-12-20은 토요일


class TestOrdering:
    """Ordering: 순서 보장"""

    def test_dates_sorted(self):
        """날짜 오름차순 정렬"""
        business = create_mock_business_info()
        biz_item = create_mock_biz_item_info()
        # 역순으로 넣어도 정렬되어야 함
        schedule = create_mock_schedule_info(dates=["2025-12-25", "2025-12-20", "2025-12-22"])

        response = build_response(business, biz_item, schedule)

        dates = [ds.date for ds in response.slots_by_date]
        assert dates == sorted(dates)

    def test_slots_sorted_by_time(self):
        """슬롯 시간순 정렬"""
        business = create_mock_business_info()
        biz_item = create_mock_biz_item_info()
        schedule = create_mock_schedule_info(dates=["2025-12-20"], slots_per_day=3)

        response = build_response(business, biz_item, schedule)

        times = [s.time for s in response.slots_by_date[0].slots]
        assert times == sorted(times)


class TestRange:
    """Range: 범위 검증"""

    def test_capacity_non_negative(self):
        """정원은 음수가 아님"""
        business = create_mock_business_info()
        biz_item = create_mock_biz_item_info()
        schedule = create_mock_schedule_info()

        response = build_response(business, biz_item, schedule)

        for date_slots in response.slots_by_date:
            for slot in date_slots.slots:
                assert slot.capacity >= 0

    def test_booked_not_exceed_capacity(self):
        """예약 수는 정원을 초과하지 않음"""
        business = create_mock_business_info()
        biz_item = create_mock_biz_item_info()
        schedule = create_mock_schedule_info()

        response = build_response(business, biz_item, schedule)

        for date_slots in response.slots_by_date:
            for slot in date_slots.slots:
                assert slot.booked <= slot.capacity


class TestExistence:
    """Existence: 존재 여부"""

    @patch('app.modules.naver_booking.routes.slot_check.NaverGraphQLClient')
    def test_empty_schedule(self, mock_client_class):
        """슬롯이 없는 경우"""
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.fetch_business_info.return_value = create_mock_business_info()
        mock_client.fetch_biz_item.return_value = create_mock_biz_item_info()

        # 빈 스케줄
        empty_schedule = ScheduleInfo(
            business_id="1269828",
            biz_item_id="6309738",
            available_dates=[],
            slots=[],
            slots_by_date={}
        )
        mock_client.fetch_schedule.return_value = empty_schedule

        response = client.get(
            "/api/v1/slots/check",
            params={"business_id": "1269828", "biz_item_id": "6309738"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_slots"] == 0
        assert data["summary"]["total_available_slots"] == 0
        assert len(data["slots_by_date"]) == 0


class TestCardinality:
    """Cardinality: 개수 검증"""

    def test_total_slots_count(self):
        """총 슬롯 수 일치"""
        business = create_mock_business_info()
        biz_item = create_mock_biz_item_info()
        schedule = create_mock_schedule_info(dates=["2025-12-20", "2025-12-21"], slots_per_day=3)

        response = build_response(business, biz_item, schedule)

        # 2일 x 3슬롯 = 6개
        assert response.summary.total_slots == 6

    def test_date_summary_matches_slots(self):
        """날짜별 요약과 슬롯 합계 일치"""
        business = create_mock_business_info()
        biz_item = create_mock_biz_item_info()
        schedule = create_mock_schedule_info(dates=["2025-12-20"], slots_per_day=3)

        response = build_response(business, biz_item, schedule)

        date_slots = response.slots_by_date[0]
        summary = date_slots.summary

        # 슬롯들의 합계와 summary 비교
        slots_capacity = sum(s.capacity for s in date_slots.slots)
        slots_booked = sum(s.booked for s in date_slots.slots)

        assert summary.total_capacity == slots_capacity
        assert summary.total_booked == slots_booked
        assert summary.total_remaining == slots_capacity - slots_booked


class TestTime:
    """Time: 시간 관련 테스트"""

    @patch('app.modules.naver_booking.routes.slot_check.NaverGraphQLClient')
    def test_target_date_parameter(self, mock_client_class):
        """target_date 파라미터 전달"""
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.fetch_business_info.return_value = create_mock_business_info()
        mock_client.fetch_biz_item.return_value = create_mock_biz_item_info()
        mock_client.fetch_schedule.return_value = create_mock_schedule_info()

        response = client.get(
            "/api/v1/slots/check",
            params={
                "business_id": "1269828",
                "biz_item_id": "6309738",
                "target_date": "2025-12-25"
            }
        )

        assert response.status_code == 200
        mock_client.fetch_schedule.assert_called_once()
        call_kwargs = mock_client.fetch_schedule.call_args.kwargs
        assert call_kwargs["start_date"] == "2025-12-25"

    def test_queried_at_present(self):
        """조회 시각이 현재 시간 근처"""
        business = create_mock_business_info()
        biz_item = create_mock_biz_item_info()
        schedule = create_mock_schedule_info()

        before = datetime.now()
        response = build_response(business, biz_item, schedule)
        after = datetime.now()

        # queried_at이 before와 after 사이
        assert before <= response.queried_at <= after


# ============================================================
# 통합 테스트
# ============================================================

class TestIntegration:
    """통합 테스트"""

    @patch('app.modules.naver_booking.routes.slot_check.NaverGraphQLClient')
    def test_full_flow_with_url(self, mock_client_class):
        """URL -> 파싱 -> API 호출 -> 응답 전체 흐름"""
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.fetch_business_info.return_value = create_mock_business_info("1269828")
        mock_client.fetch_biz_item.return_value = create_mock_biz_item_info("6309738")
        mock_client.fetch_schedule.return_value = create_mock_schedule_info(
            business_id="1269828",
            biz_item_id="6309738",
            dates=["2025-12-20", "2025-12-21", "2025-12-22"]
        )

        response = client.get(
            "/api/v1/slots/check",
            params={
                "url": "https://booking.naver.com/booking/13/bizes/1269828/items/6309738",
                "days_ahead": 14
            }
        )

        assert response.status_code == 200
        data = response.json()

        # 전체 응답 구조 검증
        assert "business" in data
        assert "biz_item" in data
        assert "summary" in data
        assert "slots_by_date" in data
        assert "queried_at" in data

        # 데이터 일관성 검증
        assert data["business"]["business_id"] == "1269828"
        assert data["biz_item"]["biz_item_id"] == "6309738"
        assert len(data["slots_by_date"]) == 3  # 3일

        # API 호출 검증
        mock_client.fetch_business_info.assert_called_once_with("1269828")
        mock_client.fetch_biz_item.assert_called_once_with("1269828", "6309738")

    @patch('app.modules.naver_booking.routes.slot_check.NaverGraphQLClient')
    def test_response_json_serializable(self, mock_client_class):
        """응답이 JSON 직렬화 가능"""
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.fetch_business_info.return_value = create_mock_business_info()
        mock_client.fetch_biz_item.return_value = create_mock_biz_item_info()
        mock_client.fetch_schedule.return_value = create_mock_schedule_info()

        response = client.get(
            "/api/v1/slots/check",
            params={"business_id": "1269828", "biz_item_id": "6309738"}
        )

        # JSON 파싱 성공하면 직렬화 가능
        data = response.json()
        assert isinstance(data, dict)


# ============================================================
# URL 파싱 엣지 케이스
# ============================================================

class TestUrlParsing:
    """URL 파싱 상세 테스트"""

    def test_parse_url_different_business_type(self):
        """다양한 business_type_id"""
        urls = [
            "https://booking.naver.com/booking/5/bizes/123/items/456",
            "https://booking.naver.com/booking/12/bizes/789/items/012",
            "https://booking.naver.com/booking/13/bizes/345/items/678",
        ]

        expected = [
            ("123", "456"),
            ("789", "012"),
            ("345", "678"),
        ]

        for url, exp in zip(urls, expected):
            result = parse_naver_url(url)
            assert result == exp

    def test_parse_url_long_ids(self):
        """긴 ID 파싱"""
        url = "https://booking.naver.com/booking/13/bizes/12345678901234/items/98765432109876"
        business_id, biz_item_id = parse_naver_url(url)

        assert business_id == "12345678901234"
        assert biz_item_id == "98765432109876"

    def test_parse_url_invalid_no_bizes(self):
        """bizes가 없는 URL"""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            parse_naver_url("https://booking.naver.com/booking/13/items/456")

        assert exc_info.value.status_code == 400

    def test_parse_url_invalid_no_items(self):
        """items가 없는 URL"""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            parse_naver_url("https://booking.naver.com/booking/13/bizes/123")

        assert exc_info.value.status_code == 400

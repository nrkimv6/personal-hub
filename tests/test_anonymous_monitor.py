"""
AnonymousMonitor 테스트
작성일: 2025-12-10
요구사항: 익명 모니터링 & 스마트 슬롯 감시 개선

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
"""

import pytest
import asyncio
import sys
from pathlib import Path
from typing import Dict, Any, List
from unittest.mock import AsyncMock, patch, MagicMock
from dataclasses import asdict

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.anonymous_monitor import (
    AnonymousMonitor,
    AvailabilityResult,
    SlotStatistics,
    CacheEntry,
    get_anonymous_monitor,
)
from app.services.naver_graphql_client import (
    NaverGraphQLClient,
    ScheduleInfo,
    ScheduleSlot,
    DualCheckResult,
)


# ============================================================
# 테스트 픽스처
# ============================================================

@pytest.fixture
def mock_schedule_slots():
    """테스트용 스케줄 슬롯 데이터"""
    return [
        ScheduleSlot(
            slot_id="slot-1",
            start_time="2025-12-15 18:00:00",
            date="2025-12-15",
            time="18:00",
            is_business_day=True,
            is_sale_day=True,
            stock=2,
            unit_stock=10,
            unit_booking_count=5,
            duration=60,
            min_booking_count=1,
            max_booking_count=10,
            prices=[{"min": 50000, "max": 50000}]
        ),
        ScheduleSlot(
            slot_id="slot-2",
            start_time="2025-12-15 19:00:00",
            date="2025-12-15",
            time="19:00",
            is_business_day=True,
            is_sale_day=True,
            stock=0,
            unit_stock=10,
            unit_booking_count=8,
            duration=60,
            min_booking_count=1,
            max_booking_count=10,
            prices=[{"min": 50000, "max": 50000}]
        ),
        ScheduleSlot(
            slot_id="slot-3",
            start_time="2025-12-15 20:00:00",
            date="2025-12-15",
            time="20:00",
            is_business_day=True,
            is_sale_day=True,
            stock=3,
            unit_stock=10,
            unit_booking_count=3,
            duration=60,
            min_booking_count=1,
            max_booking_count=10,
            prices=[{"min": 50000, "max": 50000}]
        ),
    ]


@pytest.fixture
def mock_schedule_info(mock_schedule_slots):
    """테스트용 스케줄 정보"""
    return ScheduleInfo(
        business_id="1234567",
        biz_item_id="7654321",
        available_dates=["2025-12-15"],
        slots=mock_schedule_slots,
        slots_by_date={"2025-12-15": mock_schedule_slots}
    )


@pytest.fixture
def mock_graphql_client():
    """모의 GraphQL 클라이언트"""
    client = MagicMock(spec=NaverGraphQLClient)
    client._last_used_proxy = None
    return client


@pytest.fixture
def mock_dual_result_available(mock_schedule_info):
    """재고 있고 HTTP OK인 DualCheckResult"""
    return DualCheckResult(
        can_book=True,
        schedule=mock_schedule_info,
        has_slots=True,
        http_ok=True,
        error_reason=None
    )


@pytest.fixture
def mock_dual_result_no_slots(mock_schedule_info):
    """슬롯 없는 DualCheckResult"""
    empty_schedule = ScheduleInfo(
        business_id="1234567",
        biz_item_id="7654321",
        available_dates=[],
        slots=[],
        slots_by_date={}
    )
    return DualCheckResult(
        can_book=False,
        schedule=empty_schedule,
        has_slots=False,
        http_ok=True,
        error_reason="no_slots"
    )


@pytest.fixture
def mock_dual_result_inactive(mock_schedule_info):
    """상품 비활성화인 DualCheckResult"""
    return DualCheckResult(
        can_book=False,
        schedule=mock_schedule_info,
        has_slots=True,
        http_ok=False,
        error_reason="inactive"
    )


@pytest.fixture
def anonymous_monitor(mock_graphql_client):
    """테스트용 AnonymousMonitor 인스턴스"""
    monitor = AnonymousMonitor(client=mock_graphql_client)
    return monitor


# ============================================================
# Right: 결과가 올바른가?
# ============================================================

class TestCheckAvailability:
    """check_availability 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_returns_available_when_stock_exists(
        self, anonymous_monitor, mock_graphql_client, mock_schedule_info, mock_dual_result_available
    ):
        """재고가 있을 때 available=True 반환"""
        mock_graphql_client.fetch_schedule_dual = AsyncMock(return_value=mock_dual_result_available)

        result = await anonymous_monitor.check_availability(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            target_date="2025-12-15",
            use_cache=False
        )

        assert result.available is True
        assert len(result.slots) == 2  # stock > 0인 슬롯만
        assert result.slots[0].time == "18:00"
        assert result.slots[1].time == "20:00"
        assert result.http_ok is True

    @pytest.mark.asyncio
    async def test_returns_unavailable_when_no_stock(
        self, anonymous_monitor, mock_graphql_client
    ):
        """재고가 없을 때 available=False 반환"""
        # 재고 없는 슬롯만 있는 스케줄
        no_stock_slots = [
            ScheduleSlot(
                slot_id="slot-1",
                start_time="2025-12-15 18:00:00",
                date="2025-12-15",
                time="18:00",
                is_business_day=True,
                is_sale_day=True,
                stock=0,
                unit_stock=10,
                unit_booking_count=10,
                duration=60,
                min_booking_count=1,
                max_booking_count=10,
                prices=[]
            )
        ]
        schedule = ScheduleInfo(
            business_id="1234567",
            biz_item_id="7654321",
            available_dates=[],  # 예약 가능 날짜 없음
            slots=no_stock_slots,
            slots_by_date={"2025-12-15": no_stock_slots}
        )
        dual_result = DualCheckResult(
            can_book=False,
            schedule=schedule,
            has_slots=False,
            http_ok=True,
            error_reason="no_slots"
        )
        mock_graphql_client.fetch_schedule_dual = AsyncMock(return_value=dual_result)

        result = await anonymous_monitor.check_availability(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            target_date="2025-12-15",
            use_cache=False
        )

        assert result.available is False
        assert len(result.slots) == 0

    @pytest.mark.asyncio
    async def test_returns_all_active_slots(
        self, anonymous_monitor, mock_graphql_client, mock_schedule_info, mock_dual_result_available
    ):
        """모든 활성 슬롯 반환 (예약/재고 설정된 슬롯)"""
        mock_graphql_client.fetch_schedule_dual = AsyncMock(return_value=mock_dual_result_available)

        result = await anonymous_monitor.check_availability(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            target_date="2025-12-15",
            use_cache=False
        )

        # all_active_slots에는 재고 유무와 관계없이 활성 슬롯 포함
        assert len(result.all_active_slots) == 3

    @pytest.mark.asyncio
    async def test_estimates_business_hours(
        self, anonymous_monitor, mock_graphql_client, mock_schedule_info, mock_dual_result_available
    ):
        """영업시간 추정"""
        mock_graphql_client.fetch_schedule_dual = AsyncMock(return_value=mock_dual_result_available)

        result = await anonymous_monitor.check_availability(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            target_date="2025-12-15",
            use_cache=False
        )

        assert result.estimated_hours is not None
        assert result.estimated_hours[0] == "18:00"  # 시작
        assert result.estimated_hours[1] == "20:00"  # 종료

    @pytest.mark.asyncio
    async def test_returns_unavailable_when_inactive(
        self, anonymous_monitor, mock_graphql_client, mock_dual_result_inactive
    ):
        """상품 비활성화일 때 available=False, http_ok=False 반환"""
        mock_graphql_client.fetch_schedule_dual = AsyncMock(return_value=mock_dual_result_inactive)

        result = await anonymous_monitor.check_availability(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            target_date="2025-12-15",
            use_cache=False
        )

        assert result.available is False
        assert result.http_ok is False
        # 슬롯은 있지만 예약 불가 (비활성화)
        assert len(result.slots) == 2


# ============================================================
# Boundary: 경계값 테스트
# ============================================================

class TestBoundaryConditions:
    """경계 조건 테스트"""

    @pytest.mark.asyncio
    async def test_empty_schedule_response(
        self, anonymous_monitor, mock_graphql_client
    ):
        """빈 스케줄 응답 처리 (GraphQL 실패)"""
        dual_result = DualCheckResult(
            can_book=False,
            schedule=None,
            has_slots=False,
            http_ok=True,
            error_reason="graphql_failed"
        )
        mock_graphql_client.fetch_schedule_dual = AsyncMock(return_value=dual_result)

        result = await anonymous_monitor.check_availability(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            target_date="2025-12-15",
            use_cache=False
        )

        assert result.available is False
        assert len(result.slots) == 0
        assert result.estimated_hours is None

    @pytest.mark.asyncio
    async def test_date_not_in_schedule(
        self, anonymous_monitor, mock_graphql_client, mock_schedule_info, mock_dual_result_available
    ):
        """요청한 날짜가 스케줄에 없는 경우"""
        mock_graphql_client.fetch_schedule_dual = AsyncMock(return_value=mock_dual_result_available)

        result = await anonymous_monitor.check_availability(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            target_date="2025-12-20",  # 스케줄에 없는 날짜
            use_cache=False
        )

        assert result.available is False
        assert len(result.slots) == 0


# ============================================================
# Error: 에러 조건 테스트
# ============================================================

class TestErrorHandling:
    """에러 처리 테스트"""

    @pytest.mark.asyncio
    async def test_timeout_error(
        self, anonymous_monitor, mock_graphql_client
    ):
        """타임아웃 에러 처리"""
        mock_graphql_client.fetch_schedule = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )

        result = await anonymous_monitor.check_availability(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            target_date="2025-12-15",
            use_cache=False
        )

        assert result.available is False
        assert result.error == "timeout"

    @pytest.mark.asyncio
    async def test_generic_exception(
        self, anonymous_monitor, mock_graphql_client
    ):
        """일반 예외 처리"""
        mock_graphql_client.fetch_schedule = AsyncMock(
            side_effect=Exception("Network error")
        )

        result = await anonymous_monitor.check_availability(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            target_date="2025-12-15",
            use_cache=False
        )

        assert result.available is False
        assert "Network error" in result.error


# ============================================================
# Cache: 캐시 테스트
# ============================================================

class TestCaching:
    """캐시 기능 테스트"""

    @pytest.mark.asyncio
    async def test_cache_hit(
        self, anonymous_monitor, mock_graphql_client, mock_schedule_info
    ):
        """캐시 히트 - API 재호출 없음"""
        mock_graphql_client.fetch_schedule = AsyncMock(return_value=mock_schedule_info)

        # 첫 번째 호출
        result1 = await anonymous_monitor.check_availability(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            target_date="2025-12-15",
            use_cache=True
        )

        # 두 번째 호출 (캐시 사용)
        result2 = await anonymous_monitor.check_availability(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            target_date="2025-12-15",
            use_cache=True
        )

        # API는 한 번만 호출
        assert mock_graphql_client.fetch_schedule.call_count == 1
        assert result1.available == result2.available

    @pytest.mark.asyncio
    async def test_cache_bypass(
        self, anonymous_monitor, mock_graphql_client, mock_schedule_info
    ):
        """캐시 우회 - 매번 API 호출"""
        mock_graphql_client.fetch_schedule = AsyncMock(return_value=mock_schedule_info)

        # use_cache=False로 두 번 호출
        await anonymous_monitor.check_availability(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            target_date="2025-12-15",
            use_cache=False
        )

        await anonymous_monitor.check_availability(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            target_date="2025-12-15",
            use_cache=False
        )

        # API가 두 번 호출됨
        assert mock_graphql_client.fetch_schedule.call_count == 2


# ============================================================
# AnalyzeSlots: 슬롯 분석 테스트
# ============================================================

class TestAnalyzeSlots:
    """analyze_slots 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_returns_suggested_times(
        self, anonymous_monitor, mock_graphql_client, mock_schedule_info
    ):
        """추천 시간 반환"""
        mock_graphql_client.fetch_schedule = AsyncMock(return_value=mock_schedule_info)

        result = await anonymous_monitor.analyze_slots(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            start_date="2025-12-15",
            days_ahead=7
        )

        assert "suggested_times" in result
        assert len(result["suggested_times"]) > 0

        # 예약 수가 많은 순으로 정렬됨
        if len(result["suggested_times"]) > 1:
            first = result["suggested_times"][0]
            second = result["suggested_times"][1]
            assert first.bookings >= second.bookings

    @pytest.mark.asyncio
    async def test_returns_estimated_hours(
        self, anonymous_monitor, mock_graphql_client, mock_schedule_info
    ):
        """추정 영업시간 반환"""
        mock_graphql_client.fetch_schedule = AsyncMock(return_value=mock_schedule_info)

        result = await anonymous_monitor.analyze_slots(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            start_date="2025-12-15",
            days_ahead=7
        )

        assert "estimated_hours" in result
        assert result["estimated_hours"]["start"] == "18:00"
        assert result["estimated_hours"]["end"] == "20:00"


# ============================================================
# Concurrency: 동시성 테스트
# ============================================================

class TestConcurrency:
    """동시성 제어 테스트"""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_requests(
        self, mock_graphql_client, mock_schedule_info
    ):
        """세마포어가 동시 요청 수 제한"""
        # 최대 동시 요청 수를 2로 설정
        monitor = AnonymousMonitor(client=mock_graphql_client)
        monitor._semaphore = asyncio.Semaphore(2)

        # 지연 응답 설정
        async def delayed_response(*args, **kwargs):
            await asyncio.sleep(0.1)
            return mock_schedule_info

        mock_graphql_client.fetch_schedule = AsyncMock(side_effect=delayed_response)

        # 5개 동시 요청
        tasks = [
            monitor.check_availability(
                business_type_id=13,
                business_id="1234567",
                biz_item_id=str(i),
                target_date="2025-12-15",
                use_cache=False
            )
            for i in range(5)
        ]

        results = await asyncio.gather(*tasks)

        # 모든 요청이 성공
        assert len(results) == 5
        assert all(r.available for r in results)


# ============================================================
# Singleton: 싱글톤 테스트
# ============================================================

class TestSingleton:
    """싱글톤 패턴 테스트"""

    def test_get_anonymous_monitor_returns_same_instance(self):
        """동일 인스턴스 반환"""
        # 싱글톤 인스턴스 초기화
        from app.services import anonymous_monitor as am_module
        am_module._anonymous_monitor_instance = None

        instance1 = get_anonymous_monitor()
        instance2 = get_anonymous_monitor()

        assert instance1 is instance2


# ============================================================
# CORRECT 조건 테스트
# ============================================================

class TestCorrectConditions:
    """CORRECT 조건 검증"""

    @pytest.mark.asyncio
    async def test_conformance_result_structure(
        self, anonymous_monitor, mock_graphql_client, mock_schedule_info
    ):
        """Conformance: AvailabilityResult 구조 준수"""
        mock_graphql_client.fetch_schedule = AsyncMock(return_value=mock_schedule_info)

        result = await anonymous_monitor.check_availability(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            target_date="2025-12-15",
            use_cache=False
        )

        assert isinstance(result, AvailabilityResult)
        assert hasattr(result, 'available')
        assert hasattr(result, 'slots')
        assert hasattr(result, 'all_active_slots')
        assert hasattr(result, 'estimated_hours')
        assert hasattr(result, 'error')

    @pytest.mark.asyncio
    async def test_cardinality_slot_counts(
        self, anonymous_monitor, mock_graphql_client, mock_schedule_info
    ):
        """Cardinality: 슬롯 개수 검증"""
        mock_graphql_client.fetch_schedule = AsyncMock(return_value=mock_schedule_info)

        result = await anonymous_monitor.check_availability(
            business_type_id=13,
            business_id="1234567",
            biz_item_id="7654321",
            target_date="2025-12-15",
            use_cache=False
        )

        # available slots <= all_active_slots
        assert len(result.slots) <= len(result.all_active_slots)

        # 재고 있는 슬롯만 available slots에 포함
        for slot in result.slots:
            assert slot.stock > 0

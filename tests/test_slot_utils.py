"""
app/utils/slot_utils.py 테스트

슬롯 관련 유틸리티 함수들의 순수 함수 테스트
"""
import pytest
from dataclasses import dataclass
from typing import Optional
from app.utils.slot_utils import (
    is_slot_blocked,
    is_slot_available,
    is_slot_available_from_dict,
    is_slot_available_from_obj,
    is_slot_displayable_from_dict,
    is_slot_displayable_from_obj,
    get_remaining_count
)


class TestIsSlotBlocked:
    """슬롯 차단 확인 테스트"""

    # Right - 정상 케이스
    def test_right_not_blocked_normal_range(self):
        """정상 범위 - 차단 아님"""
        blocked, reason = is_slot_blocked(min_booking_count=1, max_booking_count=10)
        assert blocked is False
        assert reason is None

    def test_right_blocked_min_greater_than_max(self):
        """min > max - 차단됨"""
        blocked, reason = is_slot_blocked(min_booking_count=10, max_booking_count=1)
        assert blocked is True
        assert "min(10) > max(1)" in reason

    def test_right_blocked_high_min_count(self):
        """min_booking_count >= 100 - 차단됨"""
        blocked, reason = is_slot_blocked(min_booking_count=100, max_booking_count=200)
        assert blocked is True
        assert "abnormally high" in reason

    def test_right_blocked_very_high_min_count(self):
        """min_booking_count = 1000 - 차단됨"""
        blocked, reason = is_slot_blocked(min_booking_count=1000, max_booking_count=1)
        assert blocked is True

    # Boundary - 경계값
    def test_boundary_none_values(self):
        """None 값들 - 차단 아님"""
        blocked, reason = is_slot_blocked(min_booking_count=None, max_booking_count=None)
        assert blocked is False
        assert reason is None

    def test_boundary_min_99_not_blocked(self):
        """min = 99 - 차단 아님 (100 미만)"""
        blocked, reason = is_slot_blocked(min_booking_count=99, max_booking_count=200)
        assert blocked is False

    def test_boundary_min_equals_max(self):
        """min == max - 차단 아님"""
        blocked, reason = is_slot_blocked(min_booking_count=5, max_booking_count=5)
        assert blocked is False


class TestIsSlotAvailable:
    """슬롯 예약 가능 여부 테스트"""

    # Right - 정상 케이스
    def test_right_available_with_stock(self):
        """재고가 있으면 예약 가능"""
        assert is_slot_available(
            stock=10, unit_stock=5, unit_booking_count=2,
            is_sale_day=True, is_unit_business_day=True
        ) is True

    def test_right_not_available_no_stock(self):
        """전체 재고 0이면 예약 불가"""
        assert is_slot_available(
            stock=0, unit_stock=5, unit_booking_count=2,
            is_sale_day=True, is_unit_business_day=True
        ) is False

    def test_right_not_available_unit_full(self):
        """슬롯별 재고가 꽉 차면 예약 불가"""
        assert is_slot_available(
            stock=10, unit_stock=5, unit_booking_count=5,
            is_sale_day=True, is_unit_business_day=True
        ) is False

    def test_right_not_available_not_sale_day(self):
        """판매일 아니면 예약 불가"""
        assert is_slot_available(
            stock=10, unit_stock=5, unit_booking_count=2,
            is_sale_day=False, is_unit_business_day=True
        ) is False

    def test_right_not_available_not_business_day(self):
        """영업 시간대 아니면 예약 불가"""
        assert is_slot_available(
            stock=10, unit_stock=5, unit_booking_count=2,
            is_sale_day=True, is_unit_business_day=False
        ) is False

    def test_right_not_available_blocked_slot(self):
        """차단된 슬롯은 예약 불가"""
        assert is_slot_available(
            stock=10, unit_stock=5, unit_booking_count=2,
            is_sale_day=True, is_unit_business_day=True,
            min_booking_count=1000, max_booking_count=1
        ) is False

    # Boundary - 경계값
    def test_boundary_exactly_one_remaining(self):
        """정확히 1개 남았을 때 예약 가능"""
        assert is_slot_available(
            stock=1, unit_stock=5, unit_booking_count=4,
            is_sale_day=True, is_unit_business_day=True
        ) is True

    def test_boundary_none_values_treated_as_zero(self):
        """None 값은 0으로 처리"""
        # stock이 None이면 0으로 처리되어 예약 불가
        assert is_slot_available(
            stock=None, unit_stock=5, unit_booking_count=2,
            is_sale_day=True, is_unit_business_day=True
        ) is False


class TestIsSlotAvailableFromDict:
    """딕셔너리 형태 슬롯 예약 가능 여부 테스트"""

    # Right - 정상 케이스 (camelCase)
    def test_right_available_camel_case(self):
        """camelCase 키로 예약 가능 확인"""
        slot = {
            'stock': 10,
            'unitStock': 5,
            'unitBookingCount': 2,
            'isSaleDay': True,
            'isUnitBusinessDay': True
        }
        assert is_slot_available_from_dict(slot) is True

    # Right - 정상 케이스 (snake_case)
    def test_right_available_snake_case(self):
        """snake_case 키로 예약 가능 확인"""
        slot = {
            'stock': 10,
            'unit_stock': 5,
            'unit_booking_count': 2,
            'is_sale_day': True,
            'is_unit_business_day': True
        }
        assert is_slot_available_from_dict(slot) is True

    def test_right_not_available_no_stock(self):
        """재고 없음 - 예약 불가"""
        slot = {
            'stock': 0,
            'unitStock': 5,
            'unitBookingCount': 2,
            'isSaleDay': True,
            'isUnitBusinessDay': True
        }
        assert is_slot_available_from_dict(slot) is False

    # Boundary - 경계값
    def test_boundary_empty_dict_defaults(self):
        """빈 딕셔너리는 기본값 사용"""
        slot = {}
        # stock=0이므로 예약 불가
        assert is_slot_available_from_dict(slot) is False

    def test_boundary_blocked_slot(self):
        """차단된 슬롯"""
        slot = {
            'stock': 10,
            'unitStock': 5,
            'unitBookingCount': 2,
            'isSaleDay': True,
            'isUnitBusinessDay': True,
            'minBookingCount': 1000,
            'maxBookingCount': 1
        }
        assert is_slot_available_from_dict(slot) is False


class TestIsSlotAvailableFromObj:
    """객체 형태 슬롯 예약 가능 여부 테스트"""

    @dataclass
    class MockSlot:
        stock: int = 0
        unit_stock: int = 0
        unit_booking_count: int = 0
        is_sale_day: bool = True
        is_unit_business_day: bool = True
        min_booking_count: Optional[int] = None
        max_booking_count: Optional[int] = None

    # Right - 정상 케이스
    def test_right_available_with_stock(self):
        """재고 있는 객체 - 예약 가능"""
        slot = self.MockSlot(
            stock=10, unit_stock=5, unit_booking_count=2,
            is_sale_day=True, is_unit_business_day=True
        )
        assert is_slot_available_from_obj(slot) is True

    def test_right_not_available_no_stock(self):
        """재고 없는 객체 - 예약 불가"""
        slot = self.MockSlot(
            stock=0, unit_stock=5, unit_booking_count=2
        )
        assert is_slot_available_from_obj(slot) is False

    # Boundary - 경계값
    def test_boundary_none_is_sale_day(self):
        """is_sale_day가 None이면 False로 처리"""
        slot = self.MockSlot(
            stock=10, unit_stock=5, unit_booking_count=2
        )
        slot.is_sale_day = None
        assert is_slot_available_from_obj(slot) is False

    def test_boundary_none_is_unit_business_day(self):
        """is_unit_business_day가 None이면 False로 처리"""
        slot = self.MockSlot(
            stock=10, unit_stock=5, unit_booking_count=2
        )
        slot.is_unit_business_day = None
        assert is_slot_available_from_obj(slot) is False


class TestIsSlotDisplayable:
    """슬롯 표시 여부 테스트"""

    # Right - 정상 케이스
    def test_right_displayable_from_dict(self):
        """영업 시간대 슬롯 - 표시"""
        slot = {'isUnitBusinessDay': True}
        assert is_slot_displayable_from_dict(slot) is True

    def test_right_not_displayable_from_dict(self):
        """비영업 시간대 슬롯 - 표시 안함"""
        slot = {'isUnitBusinessDay': False}
        assert is_slot_displayable_from_dict(slot) is False

    def test_right_displayable_snake_case(self):
        """snake_case 키 - 표시"""
        slot = {'is_unit_business_day': True}
        assert is_slot_displayable_from_dict(slot) is True

    # Boundary - 경계값
    def test_boundary_empty_dict(self):
        """빈 딕셔너리 - 기본 False"""
        assert is_slot_displayable_from_dict({}) is False

    # Object 버전 테스트
    def test_right_displayable_from_obj(self):
        """객체에서 표시 여부 확인"""
        @dataclass
        class MockSlot:
            is_unit_business_day: bool = False

        slot = MockSlot(is_unit_business_day=True)
        assert is_slot_displayable_from_obj(slot) is True


class TestGetRemainingCount:
    """남은 자리 수 계산 테스트"""

    # Right - 정상 케이스
    def test_right_remaining_count(self):
        """정상 남은 자리 계산"""
        assert get_remaining_count(unit_stock=10, unit_booking_count=3) == 7

    def test_right_all_booked(self):
        """모두 예약됨"""
        assert get_remaining_count(unit_stock=5, unit_booking_count=5) == 0

    # Boundary - 경계값
    def test_boundary_overbooked_returns_zero(self):
        """초과 예약은 0 반환"""
        assert get_remaining_count(unit_stock=5, unit_booking_count=10) == 0

    def test_boundary_zero_stock(self):
        """재고 0"""
        assert get_remaining_count(unit_stock=0, unit_booking_count=0) == 0

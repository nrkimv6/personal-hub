"""
슬롯 관련 유틸리티 함수
작성일: 2025-12-16

재고 확인 로직을 통일하여 여러 모듈에서 일관된 방식으로 사용합니다.
"""
from typing import Any, Dict, Union


def is_slot_available(
    stock: int,
    unit_stock: int,
    unit_booking_count: int,
    is_sale_day: bool = True,
    is_unit_business_day: bool = True
) -> bool:
    """
    슬롯의 예약 가능 여부를 확인합니다.

    재고 확인 조건:
    - is_unit_business_day가 True여야 함 (실제 영업하는 시간대)
    - is_sale_day가 True여야 함 (판매일이어야 함)
    - stock > 0 (전체 재고가 있어야 함)
    - (unit_stock - unit_booking_count) > 0 (슬롯별 남은 자리가 있어야 함)

    참고: isUnitBusinessDay는 실제 판매하는 시간대를 나타냄
    - True: 실제 판매 시간 (예: 11:30, 13:30, 16:30, 18:30)
    - False: 판매하지 않는 시간 (예: 00:00 ~ 11:00, 12:00, 14:00 등)

    Args:
        stock: 전체 재고
        unit_stock: 슬롯별 전체 재고
        unit_booking_count: 슬롯별 예약된 수량
        is_sale_day: 판매일 여부 (기본값: True)
        is_unit_business_day: 실제 영업 시간대 여부 (기본값: True)

    Returns:
        bool: 예약 가능 여부
    """
    # None 값 방어 처리 (API 응답에서 null이 올 수 있음)
    if stock is None:
        stock = 0
    if unit_stock is None:
        unit_stock = 0
    if unit_booking_count is None:
        unit_booking_count = 0

    # 실제 영업 시간대가 아니면 판매 안함
    if not is_unit_business_day:
        return False

    if not is_sale_day:
        return False

    remaining = unit_stock - unit_booking_count
    return stock > 0 and remaining > 0


def is_slot_available_from_dict(slot: Dict[str, Any]) -> bool:
    """
    딕셔너리 형태의 슬롯 데이터에서 예약 가능 여부를 확인합니다.

    GraphQL API 응답 또는 내부 슬롯 딕셔너리에서 사용합니다.

    Args:
        slot: 슬롯 데이터 딕셔너리
            - stock 또는 Stock: 전체 재고
            - unitStock 또는 unit_stock: 슬롯별 전체 재고
            - unitBookingCount 또는 unit_booking_count: 슬롯별 예약된 수량
            - isSaleDay 또는 is_sale_day: 판매일 여부
            - isUnitBusinessDay 또는 is_unit_business_day: 실제 영업 시간대 여부

    Returns:
        bool: 예약 가능 여부
    """
    # 다양한 키 형식 지원 (camelCase, snake_case)
    stock = slot.get('stock') or slot.get('Stock') or 0
    unit_stock = slot.get('unitStock') or slot.get('unit_stock') or 0
    unit_booking_count = slot.get('unitBookingCount') or slot.get('unit_booking_count') or 0
    is_sale_day = slot.get('isSaleDay', slot.get('is_sale_day', True))
    is_unit_business_day = slot.get('isUnitBusinessDay', slot.get('is_unit_business_day', True))

    return is_slot_available(stock, unit_stock, unit_booking_count, is_sale_day, is_unit_business_day)


def is_slot_available_from_obj(slot: Any) -> bool:
    """
    객체(dataclass 등) 형태의 슬롯 데이터에서 예약 가능 여부를 확인합니다.

    ScheduleSlot 등의 dataclass 객체에서 사용합니다.

    Args:
        slot: 슬롯 객체 (stock, unit_stock, unit_booking_count, is_sale_day, is_unit_business_day 속성 필요)

    Returns:
        bool: 예약 가능 여부
    """
    # getattr은 속성이 존재하지만 None인 경우 기본값을 사용하지 않으므로
    # None 체크를 별도로 수행
    stock = getattr(slot, 'stock', 0)
    unit_stock = getattr(slot, 'unit_stock', 0)
    unit_booking_count = getattr(slot, 'unit_booking_count', 0)
    is_sale_day = getattr(slot, 'is_sale_day', True)
    is_unit_business_day = getattr(slot, 'is_unit_business_day', True)

    # None인 경우 기본값으로 대체
    if stock is None:
        stock = 0
    if unit_stock is None:
        unit_stock = 0
    if unit_booking_count is None:
        unit_booking_count = 0
    # 판매 상태가 None이면 판매 불가로 처리
    if is_sale_day is None:
        is_sale_day = False
    if is_unit_business_day is None:
        is_unit_business_day = False

    return is_slot_available(stock, unit_stock, unit_booking_count, is_sale_day, is_unit_business_day)


def get_remaining_count(unit_stock: int, unit_booking_count: int) -> int:
    """
    슬롯의 남은 자리 수를 계산합니다.

    Args:
        unit_stock: 슬롯별 전체 재고
        unit_booking_count: 슬롯별 예약된 수량

    Returns:
        int: 남은 자리 수 (음수일 경우 0 반환)
    """
    remaining = unit_stock - unit_booking_count
    return max(0, remaining)

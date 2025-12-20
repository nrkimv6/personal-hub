"""
슬롯 관련 유틸리티 함수
작성일: 2025-12-16

재고 확인 로직을 통일하여 여러 모듈에서 일관된 방식으로 사용합니다.
"""
from typing import Any, Dict, Optional, Tuple, Union


def is_slot_blocked(
    min_booking_count: Optional[int],
    max_booking_count: Optional[int]
) -> Tuple[bool, Optional[str]]:
    """
    슬롯이 의도적으로 차단되었는지 확인합니다.

    네이버 예약에서 슬롯을 비활성화하는 방법:
    - minBookingCount > maxBookingCount 설정 (예: min=1000, max=1)
    - minBookingCount를 비정상적으로 큰 값으로 설정 (예: 1000)

    Args:
        min_booking_count: 최소 예약 인원
        max_booking_count: 최대 예약 인원

    Returns:
        Tuple[bool, Optional[str]]: (차단 여부, 차단 사유)
    """
    if min_booking_count is None or max_booking_count is None:
        return False, None

    # minBookingCount > maxBookingCount: 예약 불가능
    if min_booking_count > max_booking_count:
        return True, f"min({min_booking_count}) > max({max_booking_count})"

    # minBookingCount가 비정상적으로 큰 경우 (100 이상)
    if min_booking_count >= 100:
        return True, f"min_booking_count={min_booking_count} (abnormally high)"

    return False, None


def is_slot_available(
    stock: int,
    unit_stock: int,
    unit_booking_count: int,
    is_sale_day: bool = True,
    is_unit_business_day: bool = True,
    min_booking_count: Optional[int] = None,
    max_booking_count: Optional[int] = None
) -> bool:
    """
    슬롯의 예약 가능 여부를 확인합니다.

    재고 확인 조건:
    - 슬롯이 의도적으로 차단되지 않아야 함 (min > max 또는 min >= 100)
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
        min_booking_count: 최소 예약 인원 (옵션)
        max_booking_count: 최대 예약 인원 (옵션)

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

    # 슬롯 차단 여부 확인 (min > max 또는 min >= 100)
    is_blocked, _ = is_slot_blocked(min_booking_count, max_booking_count)
    if is_blocked:
        return False

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
            - minBookingCount 또는 min_booking_count: 최소 예약 인원
            - maxBookingCount 또는 max_booking_count: 최대 예약 인원

    Returns:
        bool: 예약 가능 여부
    """
    # 다양한 키 형식 지원 (camelCase, snake_case)
    stock = slot.get('stock') or slot.get('Stock') or 0
    unit_stock = slot.get('unitStock') or slot.get('unit_stock') or 0
    unit_booking_count = slot.get('unitBookingCount') or slot.get('unit_booking_count') or 0
    is_sale_day = slot.get('isSaleDay', slot.get('is_sale_day', True))
    is_unit_business_day = slot.get('isUnitBusinessDay', slot.get('is_unit_business_day', True))
    min_booking_count = slot.get('minBookingCount') or slot.get('min_booking_count')
    max_booking_count = slot.get('maxBookingCount') or slot.get('max_booking_count')

    return is_slot_available(
        stock, unit_stock, unit_booking_count,
        is_sale_day, is_unit_business_day,
        min_booking_count, max_booking_count
    )


def is_slot_available_from_obj(slot: Any) -> bool:
    """
    객체(dataclass 등) 형태의 슬롯 데이터에서 예약 가능 여부를 확인합니다.

    ScheduleSlot 등의 dataclass 객체에서 사용합니다.

    Args:
        slot: 슬롯 객체 (stock, unit_stock, unit_booking_count, is_sale_day, is_unit_business_day,
              min_booking_count, max_booking_count 속성 필요)

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
    min_booking_count = getattr(slot, 'min_booking_count', None)
    max_booking_count = getattr(slot, 'max_booking_count', None)

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

    return is_slot_available(
        stock, unit_stock, unit_booking_count,
        is_sale_day, is_unit_business_day,
        min_booking_count, max_booking_count
    )


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

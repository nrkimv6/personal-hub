"""
URL 빌더 유틸리티

build_naver_booking_url은 app.modules.naver_booking.utils.url_builder로 이동되었습니다.
"""
from typing import Dict, Any, Optional
import warnings as _warnings

# Re-export naver-specific builder for backward compatibility
def __getattr__(name):
    if name == 'build_naver_booking_url':
        _warnings.warn(
            "app.utils.url_builder.build_naver_booking_url은 deprecated입니다. "
            "app.modules.naver_booking.utils.url_builder를 사용하세요.",
            DeprecationWarning,
            stacklevel=2
        )
        from app.modules.naver_booking.utils.url_builder import build_naver_booking_url
        return build_naver_booking_url
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def build_coupang_url(
    product_id: str,
    date: Optional[str] = None
) -> str:
    """
    쿠팡 여행상품 URL 생성

    Args:
        product_id: 쿠팡 상품 ID
        date: 예약 날짜 (옵션)

    Returns:
        쿠팡 상품 URL
    """
    base_url = f"https://trip.coupang.com/tp/products/{product_id}"
    if date:
        return f"{base_url}?date={date}"
    return base_url


def build_monitoring_url(schedule_context: Dict[str, Any]) -> str:
    """
    일정 컨텍스트에서 모니터링 URL 생성

    Args:
        schedule_context: get_enabled_with_context()에서 반환된 일정 정보

    Returns:
        서비스 타입에 맞는 모니터링 URL
    """
    service_type = schedule_context.get("service_type", "naver")

    if service_type == "naver":
        from app.modules.naver_booking.utils.url_builder import build_naver_booking_url
        return build_naver_booking_url(
            business_type_id=schedule_context.get("business_type_id", 0),
            business_id=schedule_context["business_id"],
            biz_item_id=schedule_context["biz_item_id"],
            date=schedule_context["date"],
        )
    elif service_type == "coupang":
        return build_coupang_url(
            product_id=schedule_context["item_biz_item_id"],
            date=schedule_context["date"],
        )
    else:
        # 기본적으로 base_url 사용 (startDateTime 형식)
        base_url = schedule_context.get("base_url", "")
        date = schedule_context.get("date", "")
        if base_url:
            start_datetime = f"{date}T00%3A00%3A00%2B09%3A00"
            if "?" in base_url:
                return f"{base_url}&startDateTime={start_datetime}"
            else:
                return f"{base_url}?startDateTime={start_datetime}"
        return ""


def get_effective_booking_options(schedule_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    실제 사용할 예약 옵션 계산 (상속 규칙 적용)

    Business.booking_options (기본값)
        ↓ 오버라이드
    BizItem.booking_options_override (아이템별 설정)

    Args:
        schedule_context: get_enabled_with_context()에서 반환된 일정 정보

    Returns:
        병합된 예약 옵션
    """
    # 업체 레벨 기본값
    options = schedule_context.get("booking_options") or {}

    # 아이템 레벨 오버라이드
    item_override = schedule_context.get("booking_options_override")
    if item_override:
        options.update(item_override)

    return options

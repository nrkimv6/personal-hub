"""
DEPRECATED: app.modules.naver_booking.services.biz_item_service로 이동됨

이 모듈은 하위 호환성을 위해 유지됩니다.
"""
import warnings

warnings.warn(
    "app.services.biz_item_service는 deprecated입니다. "
    "app.modules.naver_booking.services.biz_item_service를 사용하세요.",
    DeprecationWarning,
    stacklevel=2
)

from app.modules.naver_booking.services.biz_item_service import (
    BizItemService,
    biz_item_service,
)

__all__ = ['BizItemService', 'biz_item_service']

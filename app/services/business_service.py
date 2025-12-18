"""
DEPRECATED: app.modules.naver_booking.services.business_service로 이동됨

이 모듈은 하위 호환성을 위해 유지됩니다.
"""
import warnings

warnings.warn(
    "app.services.business_service는 deprecated입니다. "
    "app.modules.naver_booking.services.business_service를 사용하세요.",
    DeprecationWarning,
    stacklevel=2
)

from app.modules.naver_booking.services.business_service import (
    BusinessService,
    business_service,
)

__all__ = ['BusinessService', 'business_service']

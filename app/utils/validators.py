"""
DEPRECATED: app.modules.naver_booking.utils.validators로 이동됨

이 모듈은 하위 호환성을 위해 유지됩니다.
새 코드에서는 app.modules.naver_booking.utils.validators를 사용하세요.
"""
import warnings

warnings.warn(
    "app.utils.validators는 deprecated입니다. "
    "app.modules.naver_booking.utils.validators를 사용하세요.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export from new location
from app.modules.naver_booking.utils.validators import (
    is_naver_full_reservation,
    is_naver_page_available,
    is_naver_content_valid,
)

__all__ = [
    'is_naver_full_reservation',
    'is_naver_page_available',
    'is_naver_content_valid',
]

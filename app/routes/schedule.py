"""
DEPRECATED: app.modules.naver_booking.routes.schedule로 이동됨

이 모듈은 하위 호환성을 위해 유지됩니다.
"""
import warnings

warnings.warn(
    "app.routes.schedule은 deprecated입니다. "
    "app.modules.naver_booking.routes.schedule을 사용하세요.",
    DeprecationWarning,
    stacklevel=2
)

from app.modules.naver_booking.routes.schedule import router

__all__ = ['router']

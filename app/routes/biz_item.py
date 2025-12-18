"""
DEPRECATED: app.modules.naver_booking.routes.biz_item으로 이동됨

이 모듈은 하위 호환성을 위해 유지됩니다.
"""
import warnings

warnings.warn(
    "app.routes.biz_item은 deprecated입니다. "
    "app.modules.naver_booking.routes.biz_item을 사용하세요.",
    DeprecationWarning,
    stacklevel=2
)

from app.modules.naver_booking.routes.biz_item import router

__all__ = ['router']

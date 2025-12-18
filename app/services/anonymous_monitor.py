"""
DEPRECATED: app.modules.naver_booking.services.anonymous_monitor로 이동됨

이 모듈은 하위 호환성을 위해 유지됩니다.
"""
import warnings

warnings.warn(
    "app.services.anonymous_monitor는 deprecated입니다. "
    "app.modules.naver_booking.services.anonymous_monitor를 사용하세요.",
    DeprecationWarning,
    stacklevel=2
)

from app.modules.naver_booking.services.anonymous_monitor import (
    AnonymousMonitor,
    get_anonymous_monitor,
    AvailabilityResult,
    SlotStatistics,
    CacheEntry,
)

__all__ = ['AnonymousMonitor', 'get_anonymous_monitor', 'AvailabilityResult', 'SlotStatistics', 'CacheEntry']

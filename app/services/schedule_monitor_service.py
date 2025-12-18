"""
DEPRECATED: app.modules.naver_booking.services.schedule_service로 이동됨

이 모듈은 하위 호환성을 위해 유지됩니다.
"""
import warnings

warnings.warn(
    "app.services.schedule_monitor_service는 deprecated입니다. "
    "app.modules.naver_booking.services.schedule_service를 사용하세요.",
    DeprecationWarning,
    stacklevel=2
)

from app.modules.naver_booking.services.schedule_service import (
    ScheduleMonitorService,
    get_schedule_monitor_service,
)

# 싱글톤 인스턴스 (하위 호환성)
schedule_monitor_service = get_schedule_monitor_service()

__all__ = ['ScheduleMonitorService', 'schedule_monitor_service', 'get_schedule_monitor_service']

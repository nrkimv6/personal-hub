"""
DEPRECATED: app.modules.naver_booking.routes.slot_check으로 이동됨

이 모듈은 하위 호환성을 위해 유지됩니다.
"""
import warnings

warnings.warn(
    "app.routes.slot_check은 deprecated입니다. "
    "app.modules.naver_booking.routes.slot_check을 사용하세요.",
    DeprecationWarning,
    stacklevel=2
)

from app.modules.naver_booking.routes.slot_check import (
    router,
    DAY_OF_WEEK_KR,
    parse_naver_url,
    build_response,
)
# 테스트 mock을 위해 NaverGraphQLClient도 re-export
from app.services.naver_graphql_client import NaverGraphQLClient, ScheduleInfo

__all__ = ['router', 'DAY_OF_WEEK_KR', 'parse_naver_url', 'build_response', 'NaverGraphQLClient', 'ScheduleInfo']

"""
DEPRECATED: app.modules.naver_booking.services.graphql_client로 이동됨

이 모듈은 하위 호환성을 위해 유지됩니다.
새 코드에서는 app.modules.naver_booking.services.graphql_client를 사용하세요.
"""
import warnings

warnings.warn(
    "app.services.naver_graphql_client는 deprecated입니다. "
    "app.modules.naver_booking.services.graphql_client를 사용하세요.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export all symbols from new location
from app.modules.naver_booking.services.graphql_client import (
    # Constants
    NAVER_GRAPHQL_ENDPOINT,
    PROXY_REQUEST_TIMEOUT,
    DIRECT_REQUEST_TIMEOUT,
    DEFAULT_USER_AGENT,
    # Data classes
    BusinessInfo,
    BizItemInfo,
    ScheduleSlot,
    ScheduleInfo,
    CacheEntry,
    DualCheckResult,
    # Main class
    NaverGraphQLClient,
    # Functions
    get_naver_graphql_client,
    set_proxy_manager,
    close_naver_graphql_client,
)

__all__ = [
    'NAVER_GRAPHQL_ENDPOINT',
    'PROXY_REQUEST_TIMEOUT',
    'DIRECT_REQUEST_TIMEOUT',
    'DEFAULT_USER_AGENT',
    'BusinessInfo',
    'BizItemInfo',
    'ScheduleSlot',
    'ScheduleInfo',
    'CacheEntry',
    'DualCheckResult',
    'NaverGraphQLClient',
    'get_naver_graphql_client',
    'set_proxy_manager',
    'close_naver_graphql_client',
]

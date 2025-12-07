"""
[하위 호환성 래퍼]

이 모듈은 app.shared.browser로 이동되었습니다.
기존 import 경로 호환성을 위해 유지됩니다.

새 코드에서는 다음을 사용하세요:
    from app.shared.browser import BrowserService, get_browser_service, set_browser_service
"""

from app.shared.browser import (
    BrowserService,
    get_browser_service,
    set_browser_service,
    ContextManager,
    TabPoolManager,
    ResourceMonitor,
    MonitoringExecutor,
    MonitoringQueue,
)

__all__ = [
    'BrowserService',
    'get_browser_service',
    'set_browser_service',
    'ContextManager',
    'TabPoolManager',
    'ResourceMonitor',
    'MonitoringExecutor',
    'MonitoringQueue',
]

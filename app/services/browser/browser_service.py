"""
[하위 호환성 래퍼]

이 모듈은 app.shared.browser.browser_service로 이동되었습니다.
기존 import 경로 호환성을 위해 유지됩니다.

새 코드에서는 다음을 사용하세요:
    from app.shared.browser import BrowserService, get_browser_service, set_browser_service
"""

from app.shared.browser.browser_service import (
    BrowserService,
    get_browser_service,
    set_browser_service,
)

# 하위 모듈에서 사용하는 import도 re-export (테스트 mock 지원)
from app.core.database import SessionLocal
from app.core.config import settings, logger

__all__ = [
    'BrowserService',
    'get_browser_service',
    'set_browser_service',
    'SessionLocal',
    'settings',
    'logger',
]

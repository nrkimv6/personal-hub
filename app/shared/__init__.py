# Shared module - 공유 서비스
# 모든 모듈에서 사용하는 공통 서비스들

# Notification을 먼저 import (browser가 의존함)
from app.shared.notification import NotificationService

# Browser는 notification import 후에 import
from app.shared.browser import (
    BrowserService,
    get_browser_service,
    set_browser_service,
)

__all__ = [
    # notification (먼저 export)
    "NotificationService",
    # browser
    "BrowserService",
    "get_browser_service",
    "set_browser_service",
]

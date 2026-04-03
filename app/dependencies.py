"""
[하위 호환성 래퍼]

이 모듈은 app.core.dependencies로 이동되었습니다.
기존 import 경로 호환성을 위해 유지됩니다.

새 코드에서는 다음을 사용하세요:
    from app.core.dependencies import get_notification_service, get_db_session

주의:
    워커/라우트 신규 코드에서 `app.dependencies`를 import하지 말고
    반드시 `app.core.dependencies`를 직접 사용하세요.
"""
from app.core.dependencies import (
    get_notification_service,
    get_db_session,
)

__all__ = ["get_notification_service", "get_db_session"]

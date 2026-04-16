"""
[하위 호환성 래퍼]

이 모듈은 app.core.config로 이동되었습니다.
기존 import 경로 호환성을 위해 유지됩니다.

`settings`는 import 시점 snapshot이고, 현재 런타임 모드가 필요하면
`get_runtime_app_mode()`를 사용해야 합니다.

새 코드에서는 다음을 사용하세요:
    from app.core.config import settings, logger, setup_logging, get_runtime_app_mode
"""
from app.core.config import (
    settings,
    logger,
    setup_logging,
    Settings,
    get_runtime_app_mode,
    normalize_app_mode,
)

__all__ = ["settings", "logger", "setup_logging", "Settings", "get_runtime_app_mode", "normalize_app_mode"]

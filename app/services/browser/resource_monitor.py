"""
[하위 호환성 래퍼]

이 모듈은 app.shared.browser.resource_monitor로 이동되었습니다.
기존 import 경로 호환성을 위해 유지됩니다.

새 코드에서는 다음을 사용하세요:
    from app.shared.browser import ResourceMonitor
"""

from app.shared.browser.resource_monitor import ResourceMonitor

# 테스트 mock 지원용 re-export
import psutil

__all__ = ['ResourceMonitor', 'psutil']

"""
[하위 호환성 래퍼]

이 모듈은 app.shared.browser.tab_pool_manager로 이동되었습니다.
기존 import 경로 호환성을 위해 유지됩니다.

새 코드에서는 다음을 사용하세요:
    from app.shared.browser import TabPoolManager
"""

from app.shared.browser.tab_pool_manager import TabPoolManager

__all__ = ['TabPoolManager']

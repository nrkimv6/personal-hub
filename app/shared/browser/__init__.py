"""
Browser Service 모듈

브라우저 관리 기능을 제공합니다.

모듈 구조:
- browser_manager.py: 브라우저 중앙 관리자 (메인 인터페이스)
- context_manager.py: 브라우저 컨텍스트 관리
- tab_pool_manager.py: 탭 풀 관리
- session_manager.py: 계정별 세션 관리 (로그인, 브라우저 열기)
- resource_monitor.py: 리소스/메모리 모니터링
"""

from .browser_manager import BrowserManager
from .context_manager import ContextManager
from .tab_pool_manager import TabPoolManager
from .session_manager import SessionManager
from .resource_monitor import ResourceMonitor

__all__ = [
    'BrowserManager',
    'ContextManager',
    'TabPoolManager',
    'SessionManager',
    'ResourceMonitor',
]

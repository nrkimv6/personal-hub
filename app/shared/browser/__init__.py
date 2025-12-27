"""
Browser Service 모듈

리팩토링된 BrowserService를 제공합니다.

모듈 구조:
- browser_manager.py: 브라우저 중앙 관리자 (워커용)
- browser_service.py: BrowserService 파사드 (메인 인터페이스)
- context_manager.py: 브라우저 컨텍스트 관리
- tab_pool_manager.py: 탭 풀 관리
- resource_monitor.py: 리소스/메모리 모니터링
- monitoring_executor.py: 모니터링 실행 로직
- monitoring_queue.py: 대기열 관리
"""

from .browser_manager import BrowserManager
from .browser_service import BrowserService, get_browser_service, set_browser_service

# 하위 모듈도 필요시 직접 import 가능
from .context_manager import ContextManager
from .tab_pool_manager import TabPoolManager
from .resource_monitor import ResourceMonitor
from .monitoring_executor import MonitoringExecutor
from .monitoring_queue import MonitoringQueue

__all__ = [
    'BrowserManager',
    'BrowserService',
    'get_browser_service',
    'set_browser_service',
    'ContextManager',
    'TabPoolManager',
    'ResourceMonitor',
    'MonitoringExecutor',
    'MonitoringQueue',
]

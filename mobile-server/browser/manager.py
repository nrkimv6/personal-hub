"""
브라우저 매니저

헤디드 브라우저의 생명주기를 관리하고, 페이지 접근/렌더링 기능을 제공합니다.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class BrowserManager(ABC):
    """브라우저 매니저 추상 클래스"""

    def __init__(self):
        self._initialized = False
        self._browser = None
        self._context = None

    @abstractmethod
    async def initialize(self) -> bool:
        """
        브라우저 인스턴스 초기화

        Returns:
            초기화 성공 여부
        """
        pass

    @abstractmethod
    async def cleanup(self):
        """브라우저 인스턴스 정리"""
        pass

    @abstractmethod
    async def is_healthy(self) -> bool:
        """
        브라우저가 정상 동작하는지 확인

        Returns:
            정상 여부
        """
        pass

    @abstractmethod
    async def fetch_html(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        wait_timeout: int = 30000,
        screenshot: bool = False
    ) -> Dict[str, Any]:
        """
        URL에 접근하여 HTML을 가져옴

        Args:
            url: 접근할 URL
            wait_for_selector: 대기할 CSS 셀렉터
            wait_timeout: 최대 대기 시간(밀리초)
            screenshot: 스크린샷 캡처 여부

        Returns:
            {
                "html": str,
                "title": str,
                "final_url": str,
                "screenshot_base64": Optional[str],
                "fetched_at": str
            }
        """
        pass

    @property
    def is_initialized(self) -> bool:
        """초기화 상태"""
        return self._initialized


# 전역 브라우저 매니저 인스턴스
_browser_manager_instance: Optional[BrowserManager] = None


def get_browser_manager() -> Optional[BrowserManager]:
    """전역 브라우저 매니저 인스턴스 반환"""
    return _browser_manager_instance


def set_browser_manager(manager: BrowserManager):
    """전역 브라우저 매니저 인스턴스 설정"""
    global _browser_manager_instance
    _browser_manager_instance = manager

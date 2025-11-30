from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from app.models.monitor import MonitorTarget
from playwright.async_api import Page
from app.services.notification_service import NotificationService

class AbstractSiteMonitor(ABC):
    """사이트 모니터링의 기본 인터페이스"""
    
    def __init__(self, notification_service=None):
        self.notification_service = notification_service or NotificationService()
    
    @abstractmethod
    async def check_status(self, target: MonitorTarget, page: Page) -> Dict[str, Any]:
        """모니터링 대상의 상태를 확인합니다."""
        pass
    
    @abstractmethod
    async def handle_status_change(self, target: MonitorTarget, new_status: Dict[str, Any]) -> None:
        """상태 변경을 처리합니다."""
        pass
    
    @abstractmethod
    async def get_interval(self, target: MonitorTarget) -> float:
        """모니터링 간격을 반환합니다."""
        pass
    
    @abstractmethod
    async def validate_target(self, target: MonitorTarget) -> bool:
        """모니터링 대상의 유효성을 검사합니다."""
        pass 
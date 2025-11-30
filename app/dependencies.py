from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.services.browser_service import BrowserService
from app.services.monitoring_system_manager import MonitoringSystemManager
from app.services.notification_service import NotificationService
from app.config import logger

# 전역 인스턴스
_browser_service = None
_monitoring_manager = None
_notification_service = None

def get_notification_service() -> NotificationService:
    """초기화된 NotificationService 인스턴스를 반환합니다."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service

async def get_browser_service() -> BrowserService:
    """초기화된 BrowserService 인스턴스를 반환합니다."""
    global _browser_service, _monitoring_manager
    logger.info("get_browser_service 호출됨")
    if _browser_service is None:
        logger.info("BrowserService 새로 생성")
        _browser_service = BrowserService()
        logger.info("BrowserService.initialize() 호출 시작")
        await _browser_service.initialize()
        logger.info("BrowserService.initialize() 호출 완료")
        
        # BrowserService가 생성된 후 MonitoringSystemManager 생성
        if _monitoring_manager is None:
            notification_service = get_notification_service()
            _monitoring_manager = MonitoringSystemManager(
                notification_service=notification_service,
                browser_service=_browser_service
            )
            # BrowserService에 MonitoringSystemManager 설정
            _browser_service.monitor_service = _monitoring_manager
    else:
        logger.info("기존 BrowserService 인스턴스 재사용")
    return _browser_service

def get_db_session() -> Session:
    return SessionLocal()

# MonitoringSystemManager 의존성 주입 함수 수정
async def get_monitoring_manager() -> MonitoringSystemManager:
    """초기화된 MonitoringSystemManager 인스턴스를 반환합니다."""
    global _monitoring_manager
    if _monitoring_manager is None:
        browser_service = await get_browser_service()
        notification_service = get_notification_service()
        _monitoring_manager = MonitoringSystemManager(
            notification_service=notification_service,
            browser_service=browser_service
        )
        # BrowserService에 MonitoringSystemManager 설정
        browser_service.monitor_service = _monitoring_manager
    return _monitoring_manager 
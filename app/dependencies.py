"""
의존성 주입 모듈

프로세스 분리 아키텍처:
    - API 서버: DB를 통해 워커와 통신, 브라우저 직접 사용 안함
    - 워커: 브라우저 서비스 직접 관리
"""
from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.services.monitoring_system_manager import MonitoringSystemManager
from app.services.notification_service import NotificationService
from app.config import logger

# 전역 인스턴스 (API 서버용 - 브라우저 서비스 없음)
_monitoring_manager = None
_notification_service = None


def get_notification_service() -> NotificationService:
    """초기화된 NotificationService 인스턴스를 반환합니다."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service


def get_db_session() -> Session:
    """DB 세션을 반환합니다."""
    return SessionLocal()


async def get_monitoring_manager() -> MonitoringSystemManager:
    """
    초기화된 MonitoringSystemManager 인스턴스를 반환합니다.

    주의: API 서버에서는 브라우저 서비스 없이 DB 작업만 수행합니다.
    브라우저 작업은 워커 프로세스에서 처리됩니다.
    """
    global _monitoring_manager
    if _monitoring_manager is None:
        notification_service = get_notification_service()
        _monitoring_manager = MonitoringSystemManager(
            notification_service=notification_service,
            browser_service=None  # API 서버에서는 브라우저 서비스 사용 안함
        )
        logger.info("API 서버용 MonitoringSystemManager 초기화 완료 (브라우저 없음)")
    return _monitoring_manager


# ============= 하위 호환성을 위한 함수들 =============
# 이 함수들은 더 이상 API 서버에서 사용되지 않지만,
# 기존 코드 호환성을 위해 유지합니다.

async def get_browser_service():
    """
    [DEPRECATED] 브라우저 서비스는 워커 프로세스에서만 사용됩니다.

    이 함수는 하위 호환성을 위해 유지되지만,
    실제 브라우저 초기화는 수행하지 않습니다.
    """
    logger.warning("get_browser_service() 호출됨 - API 서버에서는 브라우저 서비스를 사용하지 않습니다")
    logger.warning("브라우저 작업은 워커 프로세스에서 처리됩니다")
    return None

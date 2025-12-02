"""
의존성 주입 모듈

프로세스 분리 아키텍처:
    - API 서버: DB를 통해 워커와 통신, 브라우저 직접 사용 안함
    - 워커: 브라우저 서비스 직접 관리
"""
from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.services.notification_service import NotificationService
from app.config import logger

# 전역 인스턴스 (API 서버용 - 브라우저 서비스 없음)
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


async def get_browser_service():
    """
    [DEPRECATED] 브라우저 서비스는 워커 프로세스에서만 사용됩니다.

    이 함수는 하위 호환성을 위해 유지되지만,
    실제 브라우저 초기화는 수행하지 않습니다.
    """
    logger.warning("get_browser_service() 호출됨 - API 서버에서는 브라우저 서비스를 사용하지 않습니다")
    logger.warning("브라우저 작업은 워커 프로세스에서 처리됩니다")
    return None

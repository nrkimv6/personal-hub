"""
의존성 주입 모듈

프로세스 분리 아키텍처:
    - API 서버: DB를 통해 워커와 통신, 브라우저 직접 사용 안함
    - 워커: BrowserManager 직접 관리
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from sqlalchemy.orm import Session

from app.core.database import SessionLocal

if TYPE_CHECKING:
    from app.services.notification_service import NotificationService

# 전역 인스턴스 (API 서버용)
_notification_service = None


def get_notification_service() -> "NotificationService":
    """초기화된 NotificationService 인스턴스를 반환합니다."""
    from app.services.notification_service import NotificationService
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service


def get_db_session() -> Session:
    """DB 세션을 반환합니다."""
    return SessionLocal()

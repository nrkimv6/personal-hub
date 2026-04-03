"""의존성 주입 모듈.

프로세스 분리 아키텍처:
    - API 서버: DB를 통해 워커와 통신, 브라우저 직접 사용 안함
    - 워커: BrowserManager 직접 관리

DB 세션 규칙:
    - 워커/라우트의 신규 구현은 `app.core.dependencies.get_db_session()`을 사용한다.
    - `app.dependencies` 경로는 하위 호환용 래퍼이며 신규 코드 import를 금지한다.
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
    """SQLAlchemy Session 인스턴스를 반환한다.

    호출 측에서 `with get_db_session() as db:` 형태로 사용한다.
    """
    return SessionLocal()

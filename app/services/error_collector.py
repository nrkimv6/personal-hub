"""
에러 수집 서비스
시스템 전반의 에러를 중앙 집중 저장 및 알림
"""
import traceback as tb
import json
from datetime import datetime
from typing import Optional, Dict, Any
from functools import wraps
from contextlib import contextmanager
import logging

from sqlalchemy.orm import Session

from app.models.error_log import ErrorLog
from app.core.database import SessionLocal
from app.core.config import settings


# 에러 소스 상수
class ErrorSource:
    API = "api"
    WORKER = "worker"
    DATABASE = "database"
    MIGRATION = "migration"
    NAVER = "naver"
    INSTAGRAM = "instagram"
    WRITING = "writing"
    PROXY = "proxy"
    BROWSER = "browser"
    LLM = "llm"
    CRAWL = "crawl"


# 심각도 상수
class Severity:
    CRITICAL = "critical"  # 시스템 중단 수준
    ERROR = "error"        # 기능 실패
    WARNING = "warning"    # 경고 (정상 동작에는 영향 없음)


class ErrorCollector:
    """에러를 DB에 저장하고 알림을 발송하는 서비스"""

    _logger = logging.getLogger(__name__)

    @classmethod
    def capture(
        cls,
        error: Exception,
        source: str,
        severity: str = Severity.ERROR,
        context: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None,
        notify: bool = True,
    ) -> Optional[ErrorLog]:
        """
        에러를 캡처하고 DB에 저장합니다.

        Args:
            error: 발생한 예외 객체
            source: 에러 발생 위치 (ErrorSource 상수 사용)
            severity: 에러 심각도 (Severity 상수 사용)
            context: 추가 컨텍스트 정보 (schedule_id, account_id 등)
            db: SQLAlchemy 세션 (없으면 새로 생성)
            notify: Critical 에러 시 알림 발송 여부

        Returns:
            저장된 ErrorLog 객체 또는 None (저장 실패 시)
        """
        should_close_db = False
        try:
            if db is None:
                db = SessionLocal()
                should_close_db = True

            # context를 JSON 직렬화 가능한 형태로 변환
            safe_context = cls._make_serializable(context) if context else None

            error_log = ErrorLog(
                source=source,
                severity=severity,
                error_type=type(error).__name__,
                message=str(error)[:2000],  # 메시지 길이 제한
                traceback=tb.format_exc()[:10000],  # 트레이스백 길이 제한
                context=safe_context,
                created_at=datetime.utcnow(),
                resolved=False,
            )

            db.add(error_log)
            db.commit()
            db.refresh(error_log)

            cls._logger.debug(
                f"Error captured: [{severity}] {source} - {type(error).__name__}: {str(error)[:100]}"
            )

            # Critical 에러는 즉시 알림
            if notify and severity == Severity.CRITICAL:
                cls._send_critical_alert(error_log)

            return error_log

        except Exception as e:
            cls._logger.error(f"Failed to capture error: {e}")
            if should_close_db and db:
                db.rollback()
            return None
        finally:
            if should_close_db and db:
                db.close()

    @classmethod
    def capture_sync(
        cls,
        error: Exception,
        source: str,
        severity: str = Severity.ERROR,
        context: Optional[Dict[str, Any]] = None,
        notify: bool = True,
    ) -> Optional[ErrorLog]:
        """
        동기 버전의 에러 캡처 (워커용).
        내부적으로 capture()를 호출합니다.
        """
        return cls.capture(
            error=error,
            source=source,
            severity=severity,
            context=context,
            db=None,
            notify=notify,
        )

    @classmethod
    def _make_serializable(cls, obj: Any) -> Any:
        """객체를 JSON 직렬화 가능한 형태로 변환"""
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, (list, tuple)):
            return [cls._make_serializable(item) for item in obj]
        if isinstance(obj, dict):
            return {str(k): cls._make_serializable(v) for k, v in obj.items()}
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, '__dict__'):
            return str(obj)
        return str(obj)

    @classmethod
    def _send_critical_alert(cls, error_log: ErrorLog) -> None:
        """Critical 에러 알림 발송"""
        try:
            # 순환 import 방지를 위해 함수 내에서 import
            from app.shared.notification import NotificationService

            message = (
                f"[CRITICAL ERROR]\n"
                f"Source: {error_log.source}\n"
                f"Type: {error_log.error_type}\n"
                f"Message: {error_log.message[:500]}\n"
                f"Time: {error_log.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
            )

            # NotificationService 인스턴스 생성 및 알림 발송
            notification_service = NotificationService()
            # 비동기 함수를 동기적으로 호출해야 할 수 있음
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 이미 이벤트 루프가 실행 중이면 태스크로 추가
                    asyncio.create_task(
                        notification_service.send_telegram(message)
                    )
                else:
                    loop.run_until_complete(
                        notification_service.send_telegram(message)
                    )
            except RuntimeError:
                # 이벤트 루프가 없으면 새로 생성
                asyncio.run(notification_service.send_telegram(message))

        except Exception as e:
            cls._logger.error(f"Failed to send critical alert: {e}")


def capture_errors(
    source: str,
    severity: str = Severity.ERROR,
    reraise: bool = True,
    context_func=None,
):
    """
    에러를 자동으로 캡처하는 데코레이터

    Args:
        source: 에러 발생 위치
        severity: 에러 심각도
        reraise: 에러를 다시 발생시킬지 여부
        context_func: 추가 컨텍스트를 반환하는 함수 (인자를 받아 dict 반환)

    Example:
        @capture_errors(source=ErrorSource.API, severity=Severity.ERROR)
        def my_function():
            ...

        @capture_errors(source=ErrorSource.WORKER, context_func=lambda schedule: {"schedule_id": schedule.id})
        def process_schedule(schedule):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                context = None
                if context_func and args:
                    try:
                        context = context_func(*args, **kwargs)
                    except Exception:
                        pass

                ErrorCollector.capture_sync(
                    error=e,
                    source=source,
                    severity=severity,
                    context=context,
                )

                if reraise:
                    raise

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                context = None
                if context_func and args:
                    try:
                        context = context_func(*args, **kwargs)
                    except Exception:
                        pass

                ErrorCollector.capture_sync(
                    error=e,
                    source=source,
                    severity=severity,
                    context=context,
                )

                if reraise:
                    raise

        # 비동기 함수인지 확인
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


@contextmanager
def error_context(
    source: str,
    severity: str = Severity.ERROR,
    context: Optional[Dict[str, Any]] = None,
    reraise: bool = True,
):
    """
    에러를 자동으로 캡처하는 컨텍스트 매니저

    Args:
        source: 에러 발생 위치
        severity: 에러 심각도
        context: 추가 컨텍스트 정보
        reraise: 에러를 다시 발생시킬지 여부

    Example:
        with error_context(source=ErrorSource.WORKER, context={"schedule_id": 123}):
            process_something()
    """
    try:
        yield
    except Exception as e:
        ErrorCollector.capture_sync(
            error=e,
            source=source,
            severity=severity,
            context=context,
        )
        if reraise:
            raise

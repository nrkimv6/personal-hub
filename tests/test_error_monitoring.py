"""
에러 모니터링 테스트
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import Session

from app.models.error_log import ErrorLog
from app.services.error_collector import (
    ErrorCollector,
    ErrorSource,
    Severity,
    capture_errors,
    error_context,
)
from app.schemas.error_log import ErrorLogResponse, ErrorLogStatsResponse


class TestErrorLogModel:
    """ErrorLog 모델 테스트"""

    def test_create_error_log(self, db_session: Session):
        """에러 로그 생성 테스트"""
        error_log = ErrorLog(
            source=ErrorSource.API,
            severity=Severity.ERROR,
            error_type="ValueError",
            message="Test error message",
            traceback="Traceback (most recent call last)...",
            context={"schedule_id": 123},
            resolved=False,
        )
        db_session.add(error_log)
        db_session.commit()
        db_session.refresh(error_log)

        assert error_log.id is not None
        assert error_log.source == "api"
        assert error_log.severity == "error"
        assert error_log.error_type == "ValueError"
        assert error_log.resolved is False

    def test_resolve_error_log(self, db_session: Session):
        """에러 해결 처리 테스트"""
        error_log = ErrorLog(
            source=ErrorSource.WORKER,
            severity=Severity.WARNING,
            error_type="TimeoutError",
            message="Connection timed out",
            resolved=False,
        )
        db_session.add(error_log)
        db_session.commit()

        # 해결 처리
        error_log.resolved = True
        error_log.resolved_at = datetime.utcnow()
        error_log.resolved_by = "user"
        error_log.notes = "Fixed by restarting service"
        db_session.commit()
        db_session.refresh(error_log)

        assert error_log.resolved is True
        assert error_log.resolved_at is not None
        assert error_log.resolved_by == "user"


class TestErrorCollector:
    """ErrorCollector 서비스 테스트"""

    def test_capture_error(self, db_session: Session):
        """에러 캡처 테스트"""
        try:
            raise ValueError("Test error for capture")
        except Exception as e:
            error_log = ErrorCollector.capture(
                error=e,
                source=ErrorSource.API,
                severity=Severity.ERROR,
                context={"test": True},
                db=db_session,
                notify=False,
            )

        assert error_log is not None
        assert error_log.error_type == "ValueError"
        assert "Test error for capture" in error_log.message
        assert error_log.context == {"test": True}

    def test_capture_error_sync(self):
        """동기 에러 캡처 테스트"""
        try:
            raise RuntimeError("Sync test error")
        except Exception as e:
            with patch.object(ErrorCollector, 'capture') as mock_capture:
                mock_capture.return_value = MagicMock(id=1)
                error_log = ErrorCollector.capture_sync(
                    error=e,
                    source=ErrorSource.WORKER,
                    severity=Severity.CRITICAL,
                    notify=False,
                )

                mock_capture.assert_called_once()

    def test_make_serializable(self):
        """직렬화 변환 테스트"""
        test_data = {
            "string": "value",
            "number": 123,
            "datetime": datetime(2025, 1, 1, 12, 0),
            "nested": {"key": "val"},
            "list": [1, 2, 3],
        }
        result = ErrorCollector._make_serializable(test_data)

        assert result["string"] == "value"
        assert result["number"] == 123
        assert result["datetime"] == "2025-01-01T12:00:00"
        assert result["nested"] == {"key": "val"}
        assert result["list"] == [1, 2, 3]


class TestCaptureErrorsDecorator:
    """capture_errors 데코레이터 테스트"""

    def test_decorator_catches_error(self):
        """데코레이터가 에러를 캡처하는지 테스트"""
        with patch.object(ErrorCollector, 'capture_sync') as mock_capture:
            @capture_errors(source=ErrorSource.API, reraise=False)
            def failing_function():
                raise ValueError("Decorator test error")

            # 에러가 발생해도 reraise=False이므로 예외 발생하지 않음
            failing_function()
            mock_capture.assert_called_once()

    def test_decorator_reraises_error(self):
        """데코레이터가 에러를 다시 발생시키는지 테스트"""
        with patch.object(ErrorCollector, 'capture_sync'):
            @capture_errors(source=ErrorSource.API, reraise=True)
            def failing_function():
                raise ValueError("Should be reraised")

            with pytest.raises(ValueError, match="Should be reraised"):
                failing_function()

    def test_decorator_with_context_func(self):
        """컨텍스트 함수가 있는 데코레이터 테스트"""
        with patch.object(ErrorCollector, 'capture_sync') as mock_capture:
            @capture_errors(
                source=ErrorSource.WORKER,
                reraise=False,
                context_func=lambda x: {"value": x}
            )
            def process_value(value):
                raise RuntimeError("Context test")

            process_value(42)

            # context가 {"value": 42}로 전달되어야 함
            call_kwargs = mock_capture.call_args[1]
            assert call_kwargs["context"] == {"value": 42}


class TestErrorContext:
    """error_context 컨텍스트 매니저 테스트"""

    def test_context_catches_error(self):
        """컨텍스트 매니저가 에러를 캡처하는지 테스트"""
        with patch.object(ErrorCollector, 'capture_sync') as mock_capture:
            try:
                with error_context(
                    source=ErrorSource.NAVER,
                    context={"business_id": 123},
                    reraise=True,
                ):
                    raise ConnectionError("Network error")
            except ConnectionError:
                pass

            mock_capture.assert_called_once()
            call_kwargs = mock_capture.call_args[1]
            assert call_kwargs["context"] == {"business_id": 123}

    def test_context_no_error(self):
        """에러가 없을 때 컨텍스트 매니저 테스트"""
        with patch.object(ErrorCollector, 'capture_sync') as mock_capture:
            with error_context(source=ErrorSource.API):
                result = 1 + 1

            # 에러가 없으므로 capture가 호출되지 않아야 함
            mock_capture.assert_not_called()
            assert result == 2


class TestErrorSourceConstants:
    """에러 소스 상수 테스트"""

    def test_error_sources(self):
        """에러 소스 값 테스트"""
        assert ErrorSource.API == "api"
        assert ErrorSource.WORKER == "worker"
        assert ErrorSource.DATABASE == "database"
        assert ErrorSource.MIGRATION == "migration"
        assert ErrorSource.NAVER == "naver"
        assert ErrorSource.INSTAGRAM == "instagram"
        assert ErrorSource.WRITING == "writing"
        assert ErrorSource.PROXY == "proxy"
        assert ErrorSource.BROWSER == "browser"
        assert ErrorSource.LLM == "llm"
        assert ErrorSource.CRAWL == "crawl"


class TestSeverityConstants:
    """심각도 상수 테스트"""

    def test_severity_values(self):
        """심각도 값 테스트"""
        assert Severity.CRITICAL == "critical"
        assert Severity.ERROR == "error"
        assert Severity.WARNING == "warning"


# conftest.py에 db_session 픽스처가 없을 경우를 위한 간단한 픽스처
@pytest.fixture
def db_session():
    """테스트용 DB 세션"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.base import Base
    from app.models.error_log import ErrorLog

    # 인메모리 SQLite
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    yield session

    session.close()

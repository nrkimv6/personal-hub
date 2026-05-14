"""Tests for LLM Cleanup functionality."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.llm_service import LLMService


# Test fixtures
@pytest.fixture
def test_engine():
    """Create test database engine."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def test_session(test_engine):
    """Create test session."""
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def llm_service(test_session):
    """Create LLMService instance."""
    return LLMService(test_session)


class TestCleanupStaleProcessing:
    """Tests for cleanup_stale_processing()."""

    def test_right_stale_processing_changed_to_failed(self, test_session, llm_service):
        """Stale processing 요청이 failed로 변경되어야 함."""
        # Given: 11분 전에 processing 상태가 된 요청
        stale_time = datetime.now() - timedelta(minutes=11)
        request = LLMRequest(
            caller_type="test",
            caller_id="1",
            prompt="test prompt",
            status="processing",
            requested_at=stale_time,
        )
        test_session.add(request)
        test_session.commit()

        # When: cleanup 실행
        count = llm_service.cleanup_stale_processing(timeout_minutes=10)

        # Then: 1개 처리, status=failed
        assert count == 1
        test_session.refresh(request)
        assert request.status == "failed"
        assert "Stale processing" in request.error_message
        assert request.retry_count == 1

    def test_right_recent_processing_not_affected(self, test_session, llm_service):
        """최근 processing 요청은 영향받지 않아야 함."""
        # Given: 5분 전에 processing 상태가 된 요청 (타임아웃 이내)
        recent_time = datetime.now() - timedelta(minutes=5)
        request = LLMRequest(
            caller_type="test",
            caller_id="1",
            prompt="test prompt",
            status="processing",
            requested_at=recent_time,
        )
        test_session.add(request)
        test_session.commit()

        # When: cleanup 실행 (10분 타임아웃)
        count = llm_service.cleanup_stale_processing(timeout_minutes=10)

        # Then: 처리되지 않음
        assert count == 0
        test_session.refresh(request)
        assert request.status == "processing"

    def test_boundary_just_under_timeout(self, test_session, llm_service):
        """타임아웃 직전 요청은 처리되지 않아야 함."""
        # Given: 9분 59초 전 요청 (타임아웃 직전)
        just_under = datetime.now() - timedelta(minutes=9, seconds=59)
        request = LLMRequest(
            caller_type="test",
            caller_id="1",
            prompt="test prompt",
            status="processing",
            requested_at=just_under,
        )
        test_session.add(request)
        test_session.commit()

        # When: cleanup 실행 (10분 타임아웃)
        count = llm_service.cleanup_stale_processing(timeout_minutes=10)

        # Then: 타임아웃 이전이므로 처리되지 않음
        assert count == 0

    def test_right_pending_not_affected(self, test_session, llm_service):
        """pending 상태는 영향받지 않아야 함."""
        # Given: 오래된 pending 요청
        old_time = datetime.now() - timedelta(hours=1)
        request = LLMRequest(
            caller_type="test",
            caller_id="1",
            prompt="test prompt",
            status="pending",
            requested_at=old_time,
        )
        test_session.add(request)
        test_session.commit()

        # When: cleanup 실행
        count = llm_service.cleanup_stale_processing(timeout_minutes=10)

        # Then: pending은 처리되지 않음
        assert count == 0
        test_session.refresh(request)
        assert request.status == "pending"

    def test_right_deleted_not_affected(self, test_session, llm_service):
        """soft delete된 요청은 영향받지 않아야 함."""
        # Given: 삭제된 stale processing 요청
        stale_time = datetime.now() - timedelta(minutes=20)
        request = LLMRequest(
            caller_type="test",
            caller_id="1",
            prompt="test prompt",
            status="processing",
            requested_at=stale_time,
            deleted_at=datetime.now(),
        )
        test_session.add(request)
        test_session.commit()

        # When: cleanup 실행
        count = llm_service.cleanup_stale_processing(timeout_minutes=10)

        # Then: 삭제된 것은 처리되지 않음
        assert count == 0

    def test_cardinality_multiple_stale_requests(self, test_session, llm_service):
        """여러 stale 요청 모두 처리되어야 함."""
        # Given: 3개의 stale processing 요청
        stale_time = datetime.now() - timedelta(minutes=70)
        for i in range(3):
            request = LLMRequest(
                caller_type="test",
                caller_id=str(i),
                prompt="test prompt",
                status="processing",
                requested_at=stale_time,
            )
            test_session.add(request)
        test_session.commit()

        # When: cleanup 실행
        count = llm_service.cleanup_stale_processing(timeout_minutes=10)

        # Then: 모두 처리됨
        assert count == 3


class TestCleanupOldHistory:
    """Tests for cleanup_old_history()."""

    def test_right_default_soft_delete_mode(self, test_session, llm_service):
        """hard_delete 생략 시 오래된 completed 요청은 soft delete되어야 함."""
        old_time = datetime.now() - timedelta(days=8)
        request = LLMRequest(
            caller_type="test",
            caller_id="default-soft",
            prompt="test prompt",
            status="completed",
            requested_at=old_time - timedelta(hours=1),
            processed_at=old_time,
        )
        test_session.add(request)
        test_session.commit()
        request_id = request.id

        count = llm_service.cleanup_old_history(days=7)

        assert count == 1
        persisted = test_session.query(LLMRequest).filter(LLMRequest.id == request_id).first()
        assert persisted is not None
        assert persisted.deleted_at is not None

    def test_right_old_completed_deleted(self, test_session, llm_service):
        """오래된 completed 요청이 삭제되어야 함."""
        # Given: 8일 전에 완료된 요청
        old_time = datetime.now() - timedelta(days=8)
        request = LLMRequest(
            caller_type="test",
            caller_id="1",
            prompt="test prompt",
            status="completed",
            requested_at=old_time - timedelta(hours=1),
            processed_at=old_time,
        )
        test_session.add(request)
        test_session.commit()
        request_id = request.id

        # When: cleanup 실행 (7일 보관)
        count = llm_service.cleanup_old_history(days=7, hard_delete=True)

        # Then: 삭제됨
        assert count == 1
        assert test_session.query(LLMRequest).filter(LLMRequest.id == request_id).first() is None

    def test_right_old_failed_deleted(self, test_session, llm_service):
        """오래된 failed 요청이 삭제되어야 함."""
        # Given: 8일 전에 실패한 요청
        old_time = datetime.now() - timedelta(days=8)
        request = LLMRequest(
            caller_type="test",
            caller_id="1",
            prompt="test prompt",
            status="failed",
            requested_at=old_time - timedelta(hours=1),
            processed_at=old_time,
            error_message="test error",
        )
        test_session.add(request)
        test_session.commit()
        request_id = request.id

        # When: cleanup 실행
        count = llm_service.cleanup_old_history(days=7, hard_delete=True)

        # Then: 삭제됨
        assert count == 1
        assert test_session.query(LLMRequest).filter(LLMRequest.id == request_id).first() is None

    def test_right_recent_history_not_affected(self, test_session, llm_service):
        """최근 이력은 영향받지 않아야 함."""
        # Given: 3일 전에 완료된 요청
        recent_time = datetime.now() - timedelta(days=3)
        request = LLMRequest(
            caller_type="test",
            caller_id="1",
            prompt="test prompt",
            status="completed",
            requested_at=recent_time - timedelta(hours=1),
            processed_at=recent_time,
        )
        test_session.add(request)
        test_session.commit()

        # When: cleanup 실행 (7일 보관)
        count = llm_service.cleanup_old_history(days=7, hard_delete=True)

        # Then: 삭제되지 않음
        assert count == 0

    def test_right_pending_not_affected(self, test_session, llm_service):
        """pending 상태는 오래되어도 삭제되지 않아야 함."""
        # Given: 10일 전 pending 요청
        old_time = datetime.now() - timedelta(days=10)
        request = LLMRequest(
            caller_type="test",
            caller_id="1",
            prompt="test prompt",
            status="pending",
            requested_at=old_time,
        )
        test_session.add(request)
        test_session.commit()

        # When: cleanup 실행
        count = llm_service.cleanup_old_history(days=7)

        # Then: pending은 삭제되지 않음
        assert count == 0

    def test_right_soft_delete_mode(self, test_session, llm_service):
        """soft delete 모드에서는 deleted_at만 설정되어야 함."""
        # Given: 8일 전에 완료된 요청
        old_time = datetime.now() - timedelta(days=8)
        request = LLMRequest(
            caller_type="test",
            caller_id="1",
            prompt="test prompt",
            status="completed",
            requested_at=old_time - timedelta(hours=1),
            processed_at=old_time,
        )
        test_session.add(request)
        test_session.commit()

        # When: soft delete로 cleanup 실행
        count = llm_service.cleanup_old_history(days=7, hard_delete=False)

        # Then: deleted_at만 설정됨
        assert count == 1
        test_session.refresh(request)
        assert request.deleted_at is not None

    def test_right_already_deleted_not_affected(self, test_session, llm_service):
        """이미 soft delete된 요청은 영향받지 않아야 함."""
        # Given: 이미 삭제된 오래된 요청
        old_time = datetime.now() - timedelta(days=8)
        request = LLMRequest(
            caller_type="test",
            caller_id="1",
            prompt="test prompt",
            status="completed",
            requested_at=old_time - timedelta(hours=1),
            processed_at=old_time,
            deleted_at=datetime.now() - timedelta(days=1),
        )
        test_session.add(request)
        test_session.commit()

        # When: cleanup 실행
        count = llm_service.cleanup_old_history(days=7)

        # Then: 이미 삭제된 것은 처리되지 않음
        assert count == 0


class TestRunCleanup:
    """Tests for run_cleanup() combined method."""

    def test_right_runs_both_cleanups(self, test_session, llm_service):
        """stale과 history cleanup 모두 실행되어야 함."""
        # Given: stale processing 1개, old history 1개
        stale_time = datetime.now() - timedelta(minutes=70)
        old_time = datetime.now() - timedelta(days=10)

        stale_request = LLMRequest(
            caller_type="test",
            caller_id="1",
            prompt="test",
            status="processing",
            requested_at=stale_time,
        )
        old_request = LLMRequest(
            caller_type="test",
            caller_id="2",
            prompt="test",
            status="completed",
            requested_at=old_time - timedelta(hours=1),
            processed_at=old_time,
        )
        test_session.add_all([stale_request, old_request])
        test_session.commit()

        # When: run_cleanup 실행
        result = llm_service.run_cleanup()

        # Then: 둘 다 처리됨
        assert result["stale_processing"] == 1
        assert result["old_history"] == 1
        test_session.refresh(old_request)
        assert old_request.deleted_at is not None


class TestDefaultTimeoutValues:
    """Tests for default timeout constants."""

    def test_right_stale_timeout_default(self, llm_service):
        """기본 stale timeout이 65분이어야 함."""
        assert llm_service.STALE_PROCESSING_TIMEOUT_MINUTES == 65

    def test_right_history_retention_default(self, llm_service):
        """기본 이력 보관 기간이 7일이어야 함."""
        assert llm_service.HISTORY_RETENTION_DAYS == 7

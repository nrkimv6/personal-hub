"""Tests for LLM Classifier Service - RIGHT-BICEP approach."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.instagram_post import InstagramPost
from app.models.instagram_llm_request import (
    InstagramLLMClassificationRequest,
    InstagramLLMWorkerStatus,
)
from app.modules.instagram.services.llm_classifier_service import (
    LLMClassifierService,
    LLM_TRIGGER_TAGS,
)


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
def service(test_session):
    """Create LLMClassifierService instance."""
    return LLMClassifierService(test_session)


@pytest.fixture
def sample_post(test_session):
    """Create sample Instagram post."""
    post = InstagramPost(
        post_id="test_post_123",
        account="test_account",
        url="https://instagram.com/p/test",
        caption="테스트 이벤트입니다! 추첨 경품 당첨",
        collected_at=datetime.now(),
    )
    test_session.add(post)
    test_session.commit()
    return post


class TestShouldTriggerLLM:
    """should_trigger_llm 메서드 테스트."""

    def test_right_event_tag_triggers_llm(self, service):
        """event 태그가 매칭되면 LLM 트리거."""
        result = service.should_trigger_llm(["event"])
        assert result is True

    def test_right_multiple_tags_with_event_triggers_llm(self, service):
        """여러 태그 중 event가 있으면 트리거."""
        result = service.should_trigger_llm(["sale", "event", "news"])
        assert result is True

    def test_right_no_trigger_tags_returns_false(self, service):
        """트리거 태그 없으면 False."""
        result = service.should_trigger_llm(["sale", "news"])
        assert result is False

    def test_boundary_empty_tags_returns_false(self, service):
        """빈 태그 목록은 False."""
        result = service.should_trigger_llm([])
        assert result is False


class TestGetTriggerTag:
    """get_trigger_tag 메서드 테스트."""

    def test_right_returns_event_tag(self, service):
        """event 태그가 있으면 반환."""
        result = service.get_trigger_tag(["sale", "event"])
        assert result == "event"

    def test_right_returns_first_trigger_tag(self, service):
        """첫 번째 트리거 태그 반환."""
        result = service.get_trigger_tag(["event", "contest"])
        assert result == "event"

    def test_boundary_no_trigger_tag_returns_none(self, service):
        """트리거 태그 없으면 None."""
        result = service.get_trigger_tag(["sale", "news"])
        assert result is None


class TestCreateRequest:
    """create_request 메서드 테스트."""

    def test_right_creates_request(self, service, sample_post):
        """요청 생성 성공."""
        request = service.create_request(sample_post.id, "event")

        assert request is not None
        assert request.post_id == sample_post.id
        assert request.trigger_tag == "event"
        assert request.status == "pending"
        assert request.requested_by == "auto"

    def test_right_creates_manual_request(self, service, sample_post):
        """수동 요청 생성."""
        request = service.create_request(sample_post.id, "manual", "manual")

        assert request.requested_by == "manual"

    def test_boundary_duplicate_pending_returns_existing(self, service, sample_post):
        """중복 pending 요청은 기존 것 반환."""
        request1 = service.create_request(sample_post.id, "event")
        request2 = service.create_request(sample_post.id, "event")

        assert request1.id == request2.id


class TestGetPendingRequest:
    """get_pending_request 메서드 테스트."""

    def test_right_returns_oldest_pending(self, service, sample_post, test_session):
        """가장 오래된 pending 요청 반환."""
        # Create posts and requests
        post2 = InstagramPost(
            post_id="test_post_456",
            account="test",
            collected_at=datetime.now(),
        )
        test_session.add(post2)
        test_session.commit()

        request1 = service.create_request(sample_post.id, "event")
        request2 = service.create_request(post2.id, "event")

        pending = service.get_pending_request()
        assert pending.id == request1.id

    def test_boundary_no_pending_returns_none(self, service):
        """pending 요청 없으면 None."""
        result = service.get_pending_request()
        assert result is None


class TestMarkProcessing:
    """mark_processing 메서드 테스트."""

    def test_right_changes_status_to_processing(self, service, sample_post, test_session):
        """상태가 processing으로 변경."""
        request = service.create_request(sample_post.id, "event")
        service.mark_processing(request.id)

        test_session.refresh(request)
        assert request.status == "processing"


class TestMarkCompleted:
    """mark_completed 메서드 테스트."""

    def test_right_completes_with_result(self, service, sample_post, test_session):
        """결과와 함께 완료 처리."""
        request = service.create_request(sample_post.id, "event")
        result = {"organizer": "Test Co", "event_date": "2025-01-15"}

        service.mark_completed(
            request.id,
            result,
            confidence=0.9,
            prompt="test prompt",
            raw_response="test response",
        )

        test_session.refresh(request)
        assert request.status == "completed"
        assert request.confidence_score == 0.9
        assert request.processed_at is not None
        assert "Test Co" in request.llm_result


class TestMarkFailed:
    """mark_failed 메서드 테스트."""

    def test_right_marks_as_failed(self, service, sample_post, test_session):
        """실패 처리."""
        request = service.create_request(sample_post.id, "event")
        service.mark_failed(request.id, "Timeout error")

        test_session.refresh(request)
        assert request.status == "failed"
        assert request.error_message == "Timeout error"
        assert request.retry_count == 1


class TestResetToPending:
    """reset_to_pending 메서드 테스트."""

    def test_right_resets_failed_to_pending(self, service, sample_post, test_session):
        """failed 요청을 pending으로 리셋."""
        request = service.create_request(sample_post.id, "event")
        service.mark_failed(request.id, "Error")

        result = service.reset_to_pending(request.id)

        test_session.refresh(request)
        assert result is True
        assert request.status == "pending"
        assert request.error_message is None

    def test_boundary_cannot_reset_completed(self, service, sample_post):
        """completed는 리셋 불가."""
        request = service.create_request(sample_post.id, "event")
        service.mark_completed(request.id, {}, 0.5, "", "")

        result = service.reset_to_pending(request.id)
        assert result is False


class TestExecuteClaudeClassification:
    """execute_claude_classification 메서드 테스트."""

    @patch("subprocess.run")
    def test_right_successful_classification(self, mock_run, service):
        """성공적인 분류."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='```json\n{"is_event": true, "organizer": "Test", "confidence": 0.9}\n```',
            stderr="",
        )

        result = service.execute_claude_classification("테스트 이벤트")

        assert result["success"] is True
        assert result["result"]["is_event"] is True
        assert result["result"]["organizer"] == "Test"

    @patch("subprocess.run")
    def test_error_claude_cli_failure(self, mock_run, service):
        """Claude CLI 실패."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error occurred",
        )

        result = service.execute_claude_classification("테스트")

        assert result["success"] is False
        assert "Claude CLI error" in result["error"]

    @patch("subprocess.run")
    def test_error_timeout(self, mock_run, service):
        """타임아웃."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=120)

        result = service.execute_claude_classification("테스트", timeout=120)

        assert result["success"] is False
        assert "Timeout" in result["error"]

    @patch("subprocess.run")
    def test_error_cli_not_found(self, mock_run, service):
        """Claude CLI 미설치."""
        mock_run.side_effect = FileNotFoundError()

        result = service.execute_claude_classification("테스트")

        assert result["success"] is False
        assert "not found" in result["error"]


class TestParseJsonResponse:
    """_parse_json_response 메서드 테스트."""

    def test_right_parses_json_block(self, service):
        """```json 블록 파싱."""
        text = '```json\n{"key": "value"}\n```'
        result = service._parse_json_response(text)
        assert result == {"key": "value"}

    def test_right_parses_pure_json(self, service):
        """순수 JSON 파싱."""
        text = '{"key": "value"}'
        result = service._parse_json_response(text)
        assert result == {"key": "value"}

    def test_right_parses_json_in_text(self, service):
        """텍스트 내 JSON 추출."""
        text = 'Here is the result: {"key": "value"} and more text'
        result = service._parse_json_response(text)
        assert result == {"key": "value"}

    def test_error_invalid_json(self, service):
        """잘못된 JSON 에러."""
        with pytest.raises(ValueError):
            service._parse_json_response("This is not JSON")


class TestWorkerStatus:
    """워커 상태 관련 메서드 테스트."""

    def test_right_register_worker(self, service, test_session):
        """워커 등록."""
        status = service.register_worker("worker-123", 12345)

        assert status.worker_id == "worker-123"
        assert status.pid == 12345
        assert status.is_alive is True
        assert status.current_state == "idle"

    def test_right_update_heartbeat(self, service, test_session):
        """하트비트 업데이트."""
        service.register_worker("worker-123", 12345)
        old_status = service.get_worker_status()
        old_heartbeat = old_status.last_heartbeat

        import time
        time.sleep(0.1)

        service.update_heartbeat("worker-123")
        new_status = service.get_worker_status()

        assert new_status.last_heartbeat >= old_heartbeat

    def test_right_update_worker_state(self, service, test_session, sample_post):
        """워커 상태 업데이트."""
        service.register_worker("worker-123", 12345)
        request = service.create_request(sample_post.id, "event")

        service.update_worker_state("worker-123", "processing", request.id)
        status = service.get_worker_status()

        assert status.current_state == "processing"
        assert status.current_request_id == request.id

    def test_right_mark_worker_dead(self, service, test_session):
        """워커 종료 상태."""
        service.register_worker("worker-123", 12345)
        service.mark_worker_dead("worker-123")

        # get_worker_status는 is_alive=True인 워커만 반환
        status = service.get_worker_status()
        assert status is None


class TestCheckWorkerHealth:
    """check_worker_health 메서드 테스트."""

    def test_right_healthy_worker(self, service, test_session):
        """정상 워커."""
        service.register_worker("worker-123", 12345)
        health = service.check_worker_health()

        assert health["status"] == "healthy"

    def test_right_no_worker(self, service):
        """워커 없음."""
        health = service.check_worker_health()

        assert health["status"] == "no_worker"


class TestGetStats:
    """get_stats 메서드 테스트."""

    def test_right_returns_stats(self, service, sample_post, test_session):
        """통계 반환."""
        # Create some requests
        service.create_request(sample_post.id, "event")

        stats = service.get_stats()

        assert "total" in stats
        assert "pending" in stats
        assert "completed" in stats
        assert stats["pending"] >= 1


class TestIntegration:
    """통합 테스트."""

    def test_crosscheck_full_workflow(self, service, sample_post, test_session):
        """전체 워크플로우 검증."""
        # 1. 요청 생성
        request = service.create_request(sample_post.id, "event")
        assert service.get_pending_count() == 1

        # 2. 처리 시작
        service.mark_processing(request.id)
        test_session.refresh(request)
        assert request.status == "processing"

        # 3. 완료
        service.mark_completed(
            request.id,
            {"is_event": True, "organizer": "Test"},
            0.9,
            "prompt",
            "response",
        )
        test_session.refresh(request)
        assert request.status == "completed"

        # 4. 통계 확인
        stats = service.get_stats()
        assert stats["completed"] == 1
        assert stats["pending"] == 0

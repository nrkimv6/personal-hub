"""Tests for Instagram LLM Classifier Service and Claude Worker LLM Service."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.instagram_post import InstagramPost
from app.modules.claude_worker.models.llm_request import LLMRequest, LLMWorkerStatus
from app.modules.claude_worker.services.llm_service import LLMService
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
def llm_service(test_session):
    """Create LLMService instance."""
    return LLMService(test_session)


@pytest.fixture
def instagram_service(test_session):
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


# ==================== LLMService Tests ====================

class TestLLMServiceEnqueue:
    """LLMService.enqueue 메서드 테스트."""

    def test_right_creates_request(self, llm_service, test_session):
        """요청 생성 성공."""
        request = llm_service.enqueue("instagram", "123", "test prompt")

        assert request is not None
        assert request.caller_type == "instagram"
        assert request.caller_id == "123"
        assert request.prompt == "test prompt"
        assert request.status == "pending"

    def test_boundary_duplicate_pending_returns_existing(self, llm_service):
        """중복 pending 요청은 기존 것 반환."""
        request1 = llm_service.enqueue("instagram", "123", "prompt1")
        request2 = llm_service.enqueue("instagram", "123", "prompt2")

        assert request1.id == request2.id


class TestLLMServiceGetResult:
    """LLMService.get_result 메서드 테스트."""

    def test_right_returns_result(self, llm_service):
        """결과 조회."""
        llm_service.enqueue("instagram", "123", "test prompt")
        result = llm_service.get_result("instagram", "123")

        assert result is not None
        assert result.caller_id == "123"

    def test_boundary_no_result_returns_none(self, llm_service):
        """결과 없으면 None."""
        result = llm_service.get_result("instagram", "999")
        assert result is None


class TestLLMServiceGetPendingRequest:
    """LLMService.get_pending_request 메서드 테스트."""

    def test_right_returns_oldest_pending(self, llm_service):
        """가장 오래된 pending 요청 반환."""
        req1 = llm_service.enqueue("instagram", "1", "p1")
        req2 = llm_service.enqueue("instagram", "2", "p2")

        pending = llm_service.get_pending_request()
        assert pending.id == req1.id

    def test_boundary_no_pending_returns_none(self, llm_service):
        """pending 요청 없으면 None."""
        result = llm_service.get_pending_request()
        assert result is None


class TestLLMServiceMarkProcessing:
    """LLMService.mark_processing 메서드 테스트."""

    def test_right_changes_status_to_processing(self, llm_service, test_session):
        """상태가 processing으로 변경."""
        request = llm_service.enqueue("instagram", "123", "prompt")
        llm_service.mark_processing(request.id)

        test_session.refresh(request)
        assert request.status == "processing"


class TestLLMServiceMarkCompleted:
    """LLMService.mark_completed 메서드 테스트."""

    def test_right_completes_with_result(self, llm_service, test_session):
        """결과와 함께 완료 처리."""
        request = llm_service.enqueue("instagram", "123", "prompt")
        result = {"organizer": "Test Co", "event_date": "2025-01-15"}

        llm_service.mark_completed(request.id, result, "raw response")

        test_session.refresh(request)
        assert request.status == "completed"
        assert request.processed_at is not None
        assert "Test Co" in request.result


class TestLLMServiceMarkFailed:
    """LLMService.mark_failed 메서드 테스트."""

    def test_right_marks_as_failed(self, llm_service, test_session):
        """실패 처리."""
        request = llm_service.enqueue("instagram", "123", "prompt")
        llm_service.mark_failed(request.id, "Timeout error")

        test_session.refresh(request)
        assert request.status == "failed"
        assert request.error_message == "Timeout error"
        assert request.retry_count == 1


class TestLLMServiceResetToPending:
    """LLMService.reset_to_pending 메서드 테스트."""

    def test_right_resets_failed_to_pending(self, llm_service, test_session):
        """failed 요청을 pending으로 리셋."""
        request = llm_service.enqueue("instagram", "123", "prompt")
        llm_service.mark_failed(request.id, "Error")

        result = llm_service.reset_to_pending(request.id)

        test_session.refresh(request)
        assert result is True
        assert request.status == "pending"
        assert request.error_message is None

    def test_boundary_cannot_reset_completed(self, llm_service):
        """completed는 리셋 불가."""
        request = llm_service.enqueue("instagram", "123", "prompt")
        llm_service.mark_completed(request.id, {}, "")

        result = llm_service.reset_to_pending(request.id)
        assert result is False


class TestLLMServiceExecuteClaude:
    """LLMService.execute_claude 메서드 테스트."""

    @patch("subprocess.run")
    def test_right_successful_execution(self, mock_run, llm_service):
        """성공적인 실행."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='```json\n{"is_event": true, "organizer": "Test"}\n```',
            stderr="",
        )

        result = llm_service.execute_claude("테스트 프롬프트")

        assert result["success"] is True
        assert result["result"]["is_event"] is True

    @patch("subprocess.run")
    def test_error_cli_failure(self, mock_run, llm_service):
        """Claude CLI 실패."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error occurred",
        )

        result = llm_service.execute_claude("테스트")

        assert result["success"] is False
        assert "error" in result["error"].lower()

    @patch("subprocess.run")
    def test_error_timeout(self, mock_run, llm_service):
        """타임아웃."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=120)

        result = llm_service.execute_claude("테스트", timeout=120)

        assert result["success"] is False
        assert "Timeout" in result["error"]

    @patch("subprocess.run")
    def test_error_cli_not_found(self, mock_run, llm_service):
        """Claude CLI 미설치."""
        mock_run.side_effect = FileNotFoundError()

        result = llm_service.execute_claude("테스트")

        assert result["success"] is False
        assert "not found" in result["error"]


class TestLLMServiceParseJsonResponse:
    """LLMService._parse_json_response 메서드 테스트."""

    def test_right_parses_json_block(self, llm_service):
        """```json 블록 파싱."""
        text = '```json\n{"key": "value"}\n```'
        result = llm_service._parse_json_response(text)
        assert result == {"key": "value"}

    def test_right_parses_pure_json(self, llm_service):
        """순수 JSON 파싱."""
        text = '{"key": "value"}'
        result = llm_service._parse_json_response(text)
        assert result == {"key": "value"}

    def test_right_parses_json_in_text(self, llm_service):
        """텍스트 내 JSON 추출."""
        text = 'Here is the result: {"key": "value"} and more text'
        result = llm_service._parse_json_response(text)
        assert result == {"key": "value"}

    def test_error_invalid_json(self, llm_service):
        """잘못된 JSON 에러."""
        with pytest.raises(ValueError):
            llm_service._parse_json_response("This is not JSON")


class TestLLMServiceWorkerStatus:
    """워커 상태 관련 메서드 테스트."""

    def test_right_register_worker(self, llm_service, test_session):
        """워커 등록."""
        status = llm_service.register_worker("worker-123", 12345)

        assert status.worker_id == "worker-123"
        assert status.pid == 12345
        assert status.is_alive is True
        assert status.current_state == "idle"

    def test_right_update_heartbeat(self, llm_service, test_session):
        """하트비트 업데이트."""
        llm_service.register_worker("worker-123", 12345)
        old_status = llm_service.get_worker_status()
        old_heartbeat = old_status.last_heartbeat

        import time
        time.sleep(0.1)

        llm_service.update_heartbeat("worker-123")
        new_status = llm_service.get_worker_status()

        assert new_status.last_heartbeat >= old_heartbeat

    def test_right_mark_worker_dead(self, llm_service, test_session):
        """워커 종료 상태."""
        llm_service.register_worker("worker-123", 12345)
        llm_service.mark_worker_dead("worker-123")

        status = llm_service.get_worker_status()
        assert status is None


class TestLLMServiceCheckWorkerHealth:
    """check_worker_health 메서드 테스트."""

    def test_right_healthy_worker(self, llm_service, test_session):
        """정상 워커."""
        llm_service.register_worker("worker-123", 12345)
        health = llm_service.check_worker_health()

        assert health["status"] == "healthy"

    def test_right_no_worker(self, llm_service):
        """워커 없음."""
        health = llm_service.check_worker_health()

        assert health["status"] == "no_worker"


class TestLLMServiceGetStats:
    """get_stats 메서드 테스트."""

    def test_right_returns_stats(self, llm_service):
        """통계 반환."""
        llm_service.enqueue("instagram", "123", "prompt")

        stats = llm_service.get_stats()

        assert "total" in stats
        assert "pending" in stats
        assert "completed" in stats
        assert stats["pending"] >= 1


# ==================== Instagram LLMClassifierService Tests ====================

class TestInstagramShouldTriggerLLM:
    """should_trigger_llm 메서드 테스트."""

    def test_right_event_tag_triggers_llm(self, instagram_service):
        """event 태그가 매칭되면 LLM 트리거."""
        result = instagram_service.should_trigger_llm(["event"])
        assert result is True

    def test_right_multiple_tags_with_event_triggers_llm(self, instagram_service):
        """여러 태그 중 event가 있으면 트리거."""
        result = instagram_service.should_trigger_llm(["sale", "event", "news"])
        assert result is True

    def test_right_no_trigger_tags_returns_false(self, instagram_service):
        """트리거 태그 없으면 False."""
        result = instagram_service.should_trigger_llm(["sale", "news"])
        assert result is False

    def test_boundary_empty_tags_returns_false(self, instagram_service):
        """빈 태그 목록은 False."""
        result = instagram_service.should_trigger_llm([])
        assert result is False


class TestInstagramGetTriggerTag:
    """get_trigger_tag 메서드 테스트."""

    def test_right_returns_event_tag(self, instagram_service):
        """event 태그가 있으면 반환."""
        result = instagram_service.get_trigger_tag(["sale", "event"])
        assert result == "event"

    def test_boundary_no_trigger_tag_returns_none(self, instagram_service):
        """트리거 태그 없으면 None."""
        result = instagram_service.get_trigger_tag(["sale", "news"])
        assert result is None


class TestInstagramCreateRequest:
    """create_request 메서드 테스트."""

    def test_right_creates_request(self, instagram_service, sample_post):
        """요청 생성 성공."""
        request = instagram_service.create_request(sample_post.id, "event")

        assert request is not None
        assert request.caller_type == "instagram"
        assert request.caller_id == str(sample_post.id)
        assert request.status == "pending"

    def test_boundary_no_caption_returns_none(self, instagram_service, test_session):
        """caption 없으면 None."""
        post = InstagramPost(
            post_id="no_caption",
            account="test",
            collected_at=datetime.now(),
        )
        test_session.add(post)
        test_session.commit()

        request = instagram_service.create_request(post.id, "event")
        assert request is None


class TestInstagramGetResult:
    """get_result 메서드 테스트."""

    def test_right_returns_result(self, instagram_service, sample_post, llm_service):
        """결과 조회."""
        # 요청 생성
        instagram_service.create_request(sample_post.id, "event")

        # 결과 조회
        result = instagram_service.get_result(sample_post.id)

        assert result is not None
        assert result["post_id"] == sample_post.id
        assert result["status"] == "pending"


class TestInstagramGetStats:
    """get_stats 메서드 테스트."""

    def test_right_returns_instagram_only_stats(self, instagram_service, llm_service, sample_post):
        """Instagram 관련 통계만 반환."""
        # Instagram 요청
        instagram_service.create_request(sample_post.id, "event")

        # 다른 타입 요청
        llm_service.enqueue("naver", "999", "other prompt")

        stats = instagram_service.get_stats()

        assert stats["total"] == 1  # Instagram만
        assert stats["pending"] == 1


class TestIntegration:
    """통합 테스트."""

    def test_crosscheck_full_workflow(self, instagram_service, llm_service, sample_post, test_session):
        """전체 워크플로우 검증."""
        # 1. 요청 생성
        request = instagram_service.create_request(sample_post.id, "event")
        assert instagram_service.get_pending_count() == 1

        # 2. 처리 시작
        llm_service.mark_processing(request.id)
        test_session.refresh(request)
        assert request.status == "processing"

        # 3. 완료
        llm_service.mark_completed(
            request.id,
            {"is_event": True, "organizer": "Test"},
            "raw response",
        )
        test_session.refresh(request)
        assert request.status == "completed"

        # 4. 통계 확인
        stats = instagram_service.get_stats()
        assert stats["completed"] == 1
        assert stats["pending"] == 0

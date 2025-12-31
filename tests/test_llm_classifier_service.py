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
from app.modules.claude_worker.services.llm_service import (
    LLMService,
    HEARTBEAT_WARNING_THRESHOLD,
    HEARTBEAT_UNHEALTHY_THRESHOLD,
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
        """정상 워커 - heartbeat이 최근인 경우."""
        llm_service.register_worker("worker-123", 12345)
        health = llm_service.check_worker_health()

        assert health["status"] == "healthy"
        assert health["worker_id"] == "worker-123"
        assert "seconds_since_heartbeat" not in health

    def test_right_no_worker(self, llm_service):
        """워커 없음."""
        health = llm_service.check_worker_health()

        assert health["status"] == "no_worker"
        assert "활성 워커 없음" in health["message"]

    def test_right_warning_state(self, llm_service, test_session):
        """warning 상태 - heartbeat이 2분~10분 전인 경우."""
        from datetime import timedelta

        llm_service.register_worker("worker-123", 12345)

        # heartbeat을 3분 전으로 설정
        status = llm_service.get_worker_status()
        status.last_heartbeat = datetime.now() - timedelta(seconds=180)
        test_session.commit()

        health = llm_service.check_worker_health()

        assert health["status"] == "warning"
        assert health["worker_id"] == "worker-123"
        assert health["seconds_since_heartbeat"] >= 180
        assert "지연 발생" in health["message"]

    def test_right_unhealthy_state(self, llm_service, test_session):
        """unhealthy 상태 - heartbeat이 10분 이상 전인 경우."""
        from datetime import timedelta

        llm_service.register_worker("worker-123", 12345)

        # heartbeat을 15분 전으로 설정
        status = llm_service.get_worker_status()
        status.last_heartbeat = datetime.now() - timedelta(seconds=900)
        test_session.commit()

        health = llm_service.check_worker_health()

        assert health["status"] == "unhealthy"
        assert health["worker_id"] == "worker-123"
        assert health["seconds_since_heartbeat"] >= 900
        assert "재시작 필요" in health["message"]

    def test_boundary_just_under_warning_threshold(self, llm_service, test_session):
        """경계: warning 임계값 바로 아래 (healthy 유지)."""
        from datetime import timedelta

        llm_service.register_worker("worker-123", 12345)

        # heartbeat을 임계값보다 10초 적게 설정
        status = llm_service.get_worker_status()
        status.last_heartbeat = datetime.now() - timedelta(seconds=HEARTBEAT_WARNING_THRESHOLD - 10)
        test_session.commit()

        health = llm_service.check_worker_health()

        # 임계값 미만은 healthy
        assert health["status"] == "healthy"

    def test_boundary_just_over_warning_threshold(self, llm_service, test_session):
        """경계: warning 임계값 바로 초과."""
        from datetime import timedelta

        llm_service.register_worker("worker-123", 12345)

        status = llm_service.get_worker_status()
        status.last_heartbeat = datetime.now() - timedelta(seconds=HEARTBEAT_WARNING_THRESHOLD + 1)
        test_session.commit()

        health = llm_service.check_worker_health()

        assert health["status"] == "warning"

    def test_boundary_just_under_unhealthy_threshold(self, llm_service, test_session):
        """경계: unhealthy 임계값 바로 아래 (warning 유지)."""
        from datetime import timedelta

        llm_service.register_worker("worker-123", 12345)

        # heartbeat을 임계값보다 10초 적게 설정
        status = llm_service.get_worker_status()
        status.last_heartbeat = datetime.now() - timedelta(seconds=HEARTBEAT_UNHEALTHY_THRESHOLD - 10)
        test_session.commit()

        health = llm_service.check_worker_health()

        # 임계값 미만은 warning
        assert health["status"] == "warning"

    def test_boundary_just_over_unhealthy_threshold(self, llm_service, test_session):
        """경계: unhealthy 임계값 바로 초과."""
        from datetime import timedelta

        llm_service.register_worker("worker-123", 12345)

        status = llm_service.get_worker_status()
        status.last_heartbeat = datetime.now() - timedelta(seconds=HEARTBEAT_UNHEALTHY_THRESHOLD + 1)
        test_session.commit()

        health = llm_service.check_worker_health()

        assert health["status"] == "unhealthy"


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


# ==================== LLM Request Management Tests ====================

class TestLLMServiceListRequests:
    """LLMService.list_requests 메서드 테스트."""

    def test_right_list_all_requests(self, llm_service):
        """전체 요청 목록 조회."""
        llm_service.enqueue("instagram", "1", "p1", requested_by="api")
        llm_service.enqueue("instagram", "2", "p2", requested_by="scheduler")

        result = llm_service.list_requests()

        assert result["total"] == 2
        assert len(result["items"]) == 2

    def test_right_filter_by_status(self, llm_service):
        """상태별 필터링."""
        req1 = llm_service.enqueue("instagram", "1", "p1")
        llm_service.enqueue("instagram", "2", "p2")
        llm_service.mark_completed(req1.id, {}, "")

        result = llm_service.list_requests(status="pending")

        assert result["total"] == 1
        assert result["items"][0].status == "pending"

    def test_right_filter_by_caller_type(self, llm_service):
        """caller_type 필터링."""
        llm_service.enqueue("instagram", "1", "p1")
        llm_service.enqueue("naver", "1", "p2")

        result = llm_service.list_requests(caller_type="instagram")

        assert result["total"] == 1
        assert result["items"][0].caller_type == "instagram"

    def test_right_filter_by_requested_by(self, llm_service):
        """requested_by 필터링."""
        llm_service.enqueue("instagram", "1", "p1", requested_by="api")
        llm_service.enqueue("instagram", "2", "p2", requested_by="scheduler")

        result = llm_service.list_requests(requested_by="api")

        assert result["total"] == 1
        assert result["items"][0].requested_by == "api"

    def test_right_pagination(self, llm_service):
        """페이지네이션."""
        for i in range(5):
            llm_service.enqueue("instagram", str(i), f"p{i}")

        result = llm_service.list_requests(page=1, page_size=2)

        assert result["total"] == 5
        assert len(result["items"]) == 2
        assert result["pages"] == 3


class TestLLMServiceCancelRequest:
    """LLMService.cancel_request 메서드 테스트."""

    def test_right_cancel_pending_request(self, llm_service, test_session):
        """pending 요청 취소."""
        request = llm_service.enqueue("instagram", "123", "prompt")

        result = llm_service.cancel_request(request.id)

        test_session.refresh(request)
        assert result is True
        assert request.status == "cancelled"

    def test_boundary_cannot_cancel_processing(self, llm_service):
        """processing 상태 요청은 취소 불가."""
        request = llm_service.enqueue("instagram", "123", "prompt")
        llm_service.mark_processing(request.id)

        result = llm_service.cancel_request(request.id)
        assert result is False

    def test_boundary_cannot_cancel_completed(self, llm_service):
        """completed 상태 요청은 취소 불가."""
        request = llm_service.enqueue("instagram", "123", "prompt")
        llm_service.mark_completed(request.id, {}, "")

        result = llm_service.cancel_request(request.id)
        assert result is False


class TestLLMServiceDeleteRequest:
    """LLMService.delete_request 메서드 테스트."""

    def test_right_soft_delete(self, llm_service, test_session):
        """Soft delete."""
        request = llm_service.enqueue("instagram", "123", "prompt")

        result = llm_service.delete_request(request.id)

        test_session.refresh(request)
        assert result is True
        assert request.deleted_at is not None

    def test_right_hard_delete(self, llm_service, test_session):
        """Hard delete."""
        request = llm_service.enqueue("instagram", "123", "prompt")
        request_id = request.id

        result = llm_service.delete_request(request.id, hard_delete=True)

        assert result is True
        assert test_session.query(LLMRequest).filter(LLMRequest.id == request_id).first() is None

    def test_right_deleted_not_in_list(self, llm_service):
        """삭제된 요청은 목록에서 제외."""
        llm_service.enqueue("instagram", "1", "p1")
        req2 = llm_service.enqueue("instagram", "2", "p2")
        llm_service.delete_request(req2.id)

        result = llm_service.list_requests()
        assert result["total"] == 1


class TestLLMServiceBatchRetry:
    """LLMService.batch_retry 메서드 테스트."""

    def test_right_batch_retry_failed(self, llm_service, test_session):
        """실패한 요청들 일괄 재시도."""
        req1 = llm_service.enqueue("instagram", "1", "p1")
        req2 = llm_service.enqueue("instagram", "2", "p2")
        llm_service.mark_failed(req1.id, "Error 1")
        llm_service.mark_failed(req2.id, "Error 2")

        result = llm_service.batch_retry([req1.id, req2.id])

        test_session.refresh(req1)
        test_session.refresh(req2)
        assert result["success"] == 2
        assert req1.status == "pending"
        assert req2.status == "pending"

    def test_right_skip_non_failed(self, llm_service):
        """실패하지 않은 요청은 스킵."""
        req1 = llm_service.enqueue("instagram", "1", "p1")
        req2 = llm_service.enqueue("instagram", "2", "p2")
        llm_service.mark_failed(req1.id, "Error")

        result = llm_service.batch_retry([req1.id, req2.id])

        assert result["success"] == 1
        assert result["skipped"] == 1


class TestLLMServiceHistoryStats:
    """LLMService.get_history_stats 메서드 테스트."""

    def test_right_returns_daily_data(self, llm_service):
        """일별 통계 반환."""
        llm_service.enqueue("instagram", "1", "p1")
        req2 = llm_service.enqueue("instagram", "2", "p2")
        llm_service.mark_completed(req2.id, {}, "")

        result = llm_service.get_history_stats()

        assert "data" in result
        assert "summary" in result
        assert result["summary"]["total"] >= 2

    def test_right_calculates_success_rate(self, llm_service):
        """성공률 계산."""
        req1 = llm_service.enqueue("instagram", "1", "p1")
        req2 = llm_service.enqueue("instagram", "2", "p2")
        llm_service.mark_completed(req1.id, {}, "")
        llm_service.mark_failed(req2.id, "Error")

        result = llm_service.get_history_stats()

        assert result["summary"]["success_rate"] == 50.0


class TestLLMServiceCallerStats:
    """LLMService.get_caller_stats 메서드 테스트."""

    def test_right_groups_by_caller_type(self, llm_service):
        """caller_type별 그룹화."""
        llm_service.enqueue("instagram", "1", "p1")
        llm_service.enqueue("instagram", "2", "p2")
        llm_service.enqueue("naver", "1", "p3")

        result = llm_service.get_caller_stats()

        assert "instagram" in result
        assert result["instagram"]["total"] == 2
        assert "naver" in result
        assert result["naver"]["total"] == 1


class TestLLMServiceRequestedBy:
    """requested_by 및 request_source 필드 테스트."""

    def test_right_stores_requested_by(self, llm_service, test_session):
        """requested_by 저장."""
        request = llm_service.enqueue(
            "instagram", "123", "prompt",
            requested_by="scheduler",
            request_source="instagram_event",
        )

        test_session.refresh(request)
        assert request.requested_by == "scheduler"
        assert request.request_source == "instagram_event"

    def test_right_default_values(self, llm_service, test_session):
        """기본값 설정."""
        request = llm_service.enqueue("instagram", "123", "prompt")

        test_session.refresh(request)
        assert request.requested_by == "unknown"
        assert request.request_source is None

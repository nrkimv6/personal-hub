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
    """LLMExecutorBase._parse_json_response 메서드 테스트.

    _parse_json_response는 executors/base.py로 이전됨.
    LLMService 픽스처 대신 LLMExecutorBase 직접 사용.
    """

    @pytest.fixture
    def parser(self):
        from app.modules.claude_worker.services.executors.base import LLMExecutorBase
        from unittest.mock import MagicMock
        # ABC이므로 concrete 서브클래스 생성
        class _Concrete(LLMExecutorBase):
            def execute(self, prompt, **kwargs):
                return {}
        return _Concrete()

    def test_right_parses_json_block(self, parser):
        """```json 블록 파싱."""
        text = '```json\n{"key": "value"}\n```'
        result = parser._parse_json_response(text)
        assert result == {"key": "value"}

    def test_right_parses_pure_json(self, parser):
        """순수 JSON 파싱."""
        text = '{"key": "value"}'
        result = parser._parse_json_response(text)
        assert result == {"key": "value"}

    def test_right_parses_json_in_text(self, parser):
        """텍스트 내 JSON 추출."""
        text = 'Here is the result: {"key": "value"} and more text'
        result = parser._parse_json_response(text)
        assert result == {"key": "value"}

    def test_error_invalid_json(self, parser):
        """잘못된 JSON 에러."""
        with pytest.raises(ValueError):
            parser._parse_json_response("This is not JSON")


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


# ==================== Bug Fix 공통 Fixture ====================
# Base.metadata.create_all이 writing_collection_tasks.UUID 타입을 SQLite에서
# 처리하지 못하는 기존 문제 우회 — LLMRequest/LLMWorkerStatus만 생성하는 독립 엔진 사용.

@pytest.fixture
def llm_service_minimal():
    """LLMRequest/LLMWorkerStatus 테이블만 생성하는 최소 DB fixture."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.modules.claude_worker.models.llm_request import LLMRequest, LLMWorkerStatus
    from sqlalchemy import MetaData

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # LLMRequest/LLMWorkerStatus 테이블만 생성
    LLMRequest.__table__.create(bind=engine, checkfirst=True)
    LLMWorkerStatus.__table__.create(bind=engine, checkfirst=True)

    Session = sessionmaker(bind=engine)
    session = Session()
    service = LLMService(session)
    yield service
    session.close()
    engine.dispose()


# ==================== Bug Fix: exec_mode Windows 호환성 ====================

class TestExecModeWindows:
    """Bug #1 + #2: exec_mode에서 Windows .cmd 실행 및 프롬프트 임시파일 전달 검증.

    Right-BICEP + CORRECT 기반 8케이스.
    """

    def test_right_exec_mode_uses_shell_true(self, llm_service_minimal):
        """TC-1-1 Right: exec_mode=True에서 shell=True로 실행됨 (Windows .cmd 호환)."""
        import subprocess as sp

        captured = {}

        def mock_run(cmd, **kwargs):
            captured["shell"] = kwargs.get("shell")
            captured["cmd"] = cmd
            m = MagicMock()
            m.returncode = 0
            m.stdout = '{"structured_output": {"category": "여행", "confidence": 0.9}}'
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=mock_run):
            result = llm_service_minimal.execute_claude(
                prompt="테스트 프롬프트",
                cli_options={
                    "exec_mode": True,
                    "output_format": "json",
                    "json_schema": {"type": "object", "properties": {"category": {"type": "string"}}},
                },
            )

        assert captured["shell"] is True, "exec_mode에서 shell=True 이어야 함 (Windows .cmd 호환)"
        assert result["success"] is True

    def test_right_exec_mode_prompt_not_in_args(self, llm_service_minimal):
        """TC-1-2 Right: exec_mode에서 프롬프트가 -p 인수로 직접 전달되지 않음 (임시파일 경유)."""
        import subprocess as sp

        captured = {}

        def mock_run(cmd, **kwargs):
            captured["cmd"] = cmd
            m = MagicMock()
            m.returncode = 0
            m.stdout = '{"structured_output": {"category": "테스트", "confidence": 0.8}}'
            m.stderr = ""
            return m

        long_prompt = "카테고리 분류 " * 200  # 1200자 이상 한글 프롬프트

        with patch("subprocess.run", side_effect=mock_run):
            llm_service_minimal.execute_claude(
                prompt=long_prompt,
                cli_options={"exec_mode": True, "output_format": "json"},
            )

        # 명령에 프롬프트 텍스트가 직접 포함되지 않아야 함 (type file | claude 방식)
        cmd = captured.get("cmd", "")
        assert "카테고리 분류" not in cmd, "프롬프트가 명령행에 직접 포함되면 안 됨 (임시파일 경유 필요)"
        assert "type" in cmd or "cat" in cmd, "임시파일을 stdin으로 전달하는 명령 형식이어야 함"

    def test_boundary_exec_mode_long_prompt_8000chars(self, llm_service_minimal):
        """TC-1-3 Boundary: 8000자 초과 프롬프트 — Windows CMD 한계 초과해도 정상 처리."""

        def mock_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = '{"structured_output": {"category": "test", "confidence": 0.7}}'
            m.stderr = ""
            return m

        long_prompt = "가" * 8200  # Windows CMD 8191자 한계 초과

        with patch("subprocess.run", side_effect=mock_run):
            result = llm_service_minimal.execute_claude(
                prompt=long_prompt,
                cli_options={"exec_mode": True, "output_format": "json"},
            )

        # 오류 없이 처리됨
        assert result["success"] is True

    def test_boundary_exec_mode_korean_special_chars(self, llm_service_minimal):
        """TC-1-4 Boundary: 한글+특수문자+경로 혼합 프롬프트 — 인코딩 오류 없음."""
        called = {}

        def mock_run(cmd, **kwargs):
            called["encoding"] = kwargs.get("encoding")
            m = MagicMock()
            m.returncode = 0
            m.stdout = '{"structured_output": {"category": "음식/한식", "confidence": 0.85}}'
            m.stderr = ""
            return m

        prompt = "이미지 분류\n카테고리: 여행/2023\n파일: C:\\Users\\홍길동\\사진\\IMG_001.jpg\n\"따옴표\" & <태그>"

        with patch("subprocess.run", side_effect=mock_run):
            result = llm_service_minimal.execute_claude(
                prompt=prompt,
                cli_options={"exec_mode": True, "output_format": "json"},
            )

        assert called.get("encoding") == "utf-8", "UTF-8 인코딩 강제되어야 함"
        assert result["success"] is True

    def test_error_exec_mode_nonzero_returncode(self, llm_service_minimal):
        """TC-1-5 Error: exec_mode subprocess returncode=1 → success=False."""

        def mock_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 1
            m.stdout = ""
            m.stderr = "Error: Invalid model specified"
            return m

        with patch("subprocess.run", side_effect=mock_run):
            result = llm_service_minimal.execute_claude(
                prompt="test",
                cli_options={"exec_mode": True, "output_format": "json"},
            )

        assert result["success"] is False
        assert "Invalid model" in result.get("error", "")

    def test_error_exec_mode_file_not_found(self, llm_service_minimal):
        """TC-1-6 Error: exec_mode에서 claude 명령 없음 → success=False."""

        with patch("subprocess.run", side_effect=FileNotFoundError("claude not found")):
            result = llm_service_minimal.execute_claude(
                prompt="test",
                cli_options={"exec_mode": True, "output_format": "json"},
            )

        assert result["success"] is False

    def test_correct_env_vars_cleaned(self, llm_service_minimal):
        """TC-1-7 CORRECT: exec_mode에서 nested session 방지 환경변수 제거됨."""
        import os

        captured_env = {}

        def mock_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            m = MagicMock()
            m.returncode = 0
            m.stdout = '{"structured_output": {"category": "test", "confidence": 0.9}}'
            m.stderr = ""
            return m

        original_env = os.environ.copy()
        os.environ["CLAUDECODE"] = "1"
        os.environ["CLAUDE_CODE_SESSION"] = "abc123"
        os.environ["CLAUDE_CODE_ENTRYPOINT"] = "test"

        try:
            with patch("subprocess.run", side_effect=mock_run):
                llm_service_minimal.execute_claude(
                    prompt="test",
                    cli_options={"exec_mode": True, "output_format": "json"},
                )
        finally:
            # 환경 복구
            for k in ("CLAUDECODE", "CLAUDE_CODE_SESSION", "CLAUDE_CODE_ENTRYPOINT"):
                os.environ.pop(k, None)
            os.environ.update(original_env)

        assert "CLAUDECODE" not in captured_env, "CLAUDECODE가 subprocess env에 있으면 안 됨"
        assert "CLAUDE_CODE_SESSION" not in captured_env
        assert "CLAUDE_CODE_ENTRYPOINT" not in captured_env

    def test_inverse_non_exec_mode_uses_shell_true(self, llm_service_minimal):
        """TC-1-8 Inverse: exec_mode=False(기본)일 때도 shell=True 사용."""
        captured = {}

        def mock_run(cmd, **kwargs):
            captured["shell"] = kwargs.get("shell")
            m = MagicMock()
            m.returncode = 0
            m.stdout = '{"category": "test", "confidence": 0.9}'
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=mock_run):
            llm_service_minimal.execute_claude(
                prompt="test",
                parse_json=True,
            )

        assert captured["shell"] is True, "기본(A 방식)도 shell=True이어야 함"


# ==================== Bug Fix: structured_output fallback ====================

class TestStructuredOutputFallback:
    """Bug #3: structured_output 없는 경우 전체 JSON fallback 수정 검증.

    Right-BICEP + CORRECT 기반 7케이스.
    """

    def _run_with_stdout(self, stdout_str: str) -> dict:
        """공통 헬퍼: 주어진 stdout 응답으로 execute_claude 실행 (LLMService 내부 생성)."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.modules.claude_worker.models.llm_request import LLMRequest, LLMWorkerStatus
        from app.modules.claude_worker.services.llm_service import LLMService

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        LLMRequest.__table__.create(bind=engine, checkfirst=True)
        LLMWorkerStatus.__table__.create(bind=engine, checkfirst=True)
        session = sessionmaker(bind=engine)()
        service = LLMService(session)

        def mock_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = stdout_str
            m.stderr = ""
            return m

        try:
            with patch("subprocess.run", side_effect=mock_run):
                return service.execute_claude(
                    prompt="test",
                    cli_options={
                        "exec_mode": True,
                        "output_format": "json",
                        "json_schema": {"type": "object", "properties": {"category": {"type": "string"}}},
                    },
                )
        finally:
            session.close()
            engine.dispose()

    def test_right_structured_output_present(self):
        """TC-2-1 Right: structured_output 필드 정상 존재 → 해당 값 반환."""
        result = self._run_with_stdout(
            '{"structured_output": {"category": "여행", "confidence": 0.9}, "type": "result"}',
        )

        assert result["success"] is True
        assert result["result"]["category"] == "여행"
        assert result["result"]["confidence"] == 0.9

    def test_right_result_field_is_dict(self):
        """TC-2-2 Right: result 필드가 dict → 해당 값 반환."""
        result = self._run_with_stdout(
            '{"result": {"category": "음식", "confidence": 0.8}, "type": "result"}',
        )

        assert result["success"] is True
        assert result["result"]["category"] == "음식"

    def test_right_result_field_is_json_string(self):
        """TC-2-3 Right: result 필드가 JSON 문자열 → 파싱 후 반환."""
        result = self._run_with_stdout(
            '{"result": "{\\"category\\": \\"가족\\", \\"confidence\\": 0.7}", "type": "result"}',
        )

        assert result["success"] is True
        assert result["result"]["category"] == "가족"

    def test_error_no_structured_output_no_result(self):
        """TC-2-4 Error: structured_output/result 모두 없음 → success=False (Bug #3 핵심)."""
        result = self._run_with_stdout(
            '{"type": "result", "subtype": "success", "cost_usd": 0.001, "is_error": false}',
        )

        # Bug #3 수정 전: success=True, result=전체JSON → category="" → 분류 실패
        # Bug #3 수정 후: success=False → 명시적 실패
        assert result["success"] is False
        assert "structured_output" in result.get("error", "") or "result" in result.get("error", "")

    def test_error_structured_output_empty_dict(self):
        """TC-2-5 Error: structured_output == {} (빈 딕셔너리) → fallback 시도."""
        result = self._run_with_stdout(
            '{"structured_output": {}, "type": "result"}',
        )

        # {} 는 falsy → result 필드 fallback → 없으면 success=False
        assert result["success"] is False or result.get("result") == {}

    def test_boundary_raw_response_not_json(self):
        """TC-2-6 Boundary: stdout 자체가 JSON 아님 → success=False."""
        result = self._run_with_stdout(
            "Processing image... please wait",
        )

        assert result["success"] is False
        assert "JSON" in result.get("error", "") or "파싱" in result.get("error", "")

    def test_correct_category_extracted_end_to_end(self):
        """TC-2-7 CORRECT: exec_mode → structured_output → category 정상 추출 E2E."""
        result = self._run_with_stdout(
            '{"structured_output": {"category": "여행/국내/서울", "confidence": 0.95, "reasoning": "서울 풍경"}, "type": "result", "cost_usd": 0.002}',
        )

        assert result["success"] is True
        assert result["result"]["category"] == "여행/국내/서울"
        assert result["result"]["confidence"] == 0.95


class TestQuotaWarnLog:
    """TC-Right/Boundary: quota pause 시 경고 로그 출력 검증."""

    @pytest.fixture
    def service(self, test_session):
        return LLMClassifierService(test_session)

    @pytest.fixture
    def post(self, test_session):
        p = InstagramPost(
            post_id="qw_test_001",
            caption="quota warn test caption",
            account="test_user",
        )
        test_session.add(p)
        test_session.commit()
        return p

    def test_create_request_logs_warning_when_quota_paused(self, service, post, caplog):
        """TC-Right: create_request() 호출 시 quota pause 상태 → logger.warning 호출."""
        from datetime import timedelta

        paused_until = datetime.now() + timedelta(hours=3)

        with patch.object(service._llm_service, "get_provider_quota_pause", return_value=paused_until):
            with patch.object(service._llm_service, "enqueue", return_value=MagicMock(id=1)):
                import logging
                with caplog.at_level(logging.WARNING, logger="instagram.llm_classifier"):
                    service.create_request(post.id, "event", provider="claude")

        assert any("[QUOTA_WARN]" in r.message for r in caplog.records)

    def test_create_requests_batch_logs_warning_once(self, service, test_session, caplog):
        """TC-Right: create_requests_batch() 10건 → warning 로그 1회만 출력 (중복 방지)."""
        from datetime import timedelta

        paused_until = datetime.now() + timedelta(hours=3)

        posts = []
        for i in range(3):
            p = InstagramPost(
                post_id=f"batch_qw_{i}",
                caption=f"caption {i}",
                account="test_user",
            )
            test_session.add(p)
            posts.append(p)
        test_session.commit()
        post_ids = [p.id for p in posts]

        with patch.object(service._llm_service, "get_provider_quota_pause", return_value=paused_until):
            with patch.object(service._llm_service, "enqueue", return_value=MagicMock(id=99)):
                import logging
                with caplog.at_level(logging.WARNING, logger="instagram.llm_classifier"):
                    service.create_requests_batch(post_ids, provider="claude")

        quota_warns = [r for r in caplog.records if "[QUOTA_WARN]" in r.message and "일괄" in r.message]
        assert len(quota_warns) == 1

    def test_create_request_no_warning_when_quota_not_paused(self, service, post, caplog):
        """TC-Boundary: get_provider_quota_pause() None 반환 시 → warning 없음."""
        with patch.object(service._llm_service, "get_provider_quota_pause", return_value=None):
            with patch.object(service._llm_service, "enqueue", return_value=MagicMock(id=1)):
                import logging
                with caplog.at_level(logging.WARNING, logger="instagram.llm_classifier"):
                    service.create_request(post.id, "event", provider="claude")

        quota_warns = [r for r in caplog.records if "[QUOTA_WARN]" in r.message]
        assert len(quota_warns) == 0

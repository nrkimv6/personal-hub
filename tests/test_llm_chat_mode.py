"""
LLM Chat Mode 단위 테스트 (RIGHT-BICEP + Correct)

chat mode 분기, 위임 로직, JSON 파싱 동작을 검증합니다.
패턴: in-memory SQLite + LLMService 직접 호출 + AsyncMock
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.worker.chat_executor import _extract_last_json


# ========== Fixtures ==========

@pytest.fixture(scope="module")
def engine():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    LLMRequest.__table__.create(bind=e, checkfirst=True)
    return e


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def service(db):
    return LLMService(db)


# ========== TC 17: mode 기본값 "single" ==========

def test_enqueue_mode_single_right(service, db):
    req = service.enqueue(
        caller_type="test",
        caller_id="tc17",
        prompt="hello",
        mode="single",
        provider="claude",
    )
    db.refresh(req)
    assert req.mode == "single"


# ========== TC 18: mode="chat" 저장 확인 ==========

def test_enqueue_mode_chat_right(service, db):
    req = service.enqueue(
        caller_type="test",
        caller_id="tc18",
        prompt="hello",
        mode="chat",
        provider="claude",
    )
    db.refresh(req)
    assert req.mode == "chat"


# ========== TC 19: mode 파라미터 생략 시 기본값 "single" ==========

def test_enqueue_mode_boundary_default(service, db):
    req = service.enqueue(
        caller_type="test",
        caller_id="tc19",
        prompt="hello",
        provider="claude",
    )
    db.refresh(req)
    assert req.mode == "single"


# ========== TC 20: _delegate_to_chat_executor Redis LPUSH 호출 확인 ==========

@pytest.mark.asyncio
async def test_delegate_to_chat_executor_right(service, db):
    req = service.enqueue(
        caller_type="test",
        caller_id="tc20",
        prompt="do something",
        mode="chat",
        provider="claude",
    )
    db.refresh(req)

    from app.modules.claude_worker.worker.worker import LLMWorker

    worker = LLMWorker.__new__(LLMWorker)
    worker._update_worker_state = MagicMock()

    mock_redis = AsyncMock()
    mock_redis.lpush = AsyncMock()

    with patch("app.shared.redis.client.RedisClient.get_client", new=AsyncMock(return_value=mock_redis)):
        await worker._delegate_to_chat_executor(req, service)

    mock_redis.lpush.assert_called_once()
    call_args = mock_redis.lpush.call_args
    assert call_args[0][0] == "llm-chat:commands"

    payload = json.loads(call_args[0][1])
    assert payload["request_id"] == req.id
    assert payload["prompt"] == "do something"

    db.refresh(req)
    assert req.status == "processing"


# ========== TC 21: 위임 후 _execute_request 미호출 확인 ==========

@pytest.mark.asyncio
async def test_delegate_no_block_right(service, db):
    req = service.enqueue(
        caller_type="test",
        caller_id="tc21",
        prompt="chat req",
        mode="chat",
        provider="claude",
    )
    db.refresh(req)

    from app.modules.claude_worker.worker.worker import LLMWorker

    worker = LLMWorker.__new__(LLMWorker)
    worker._update_worker_state = MagicMock()
    worker._execute_request = AsyncMock()

    mock_redis = AsyncMock()

    with patch("app.shared.redis.client.RedisClient.get_client", new=AsyncMock(return_value=mock_redis)):
        await worker._delegate_to_chat_executor(req, service)

    worker._execute_request.assert_not_called()


# ========== TC A1-R: mark_completed가 result={} + raw_response 정상 호출 ==========

def test_chat_session_mark_completed_R_passes_empty_result_dict(service, db):
    """RIGHT: chat 완료 경로에서 mark_completed가 result={} + raw_response로 정상 호출되는지 검증"""
    req = service.enqueue(
        caller_type="test", caller_id="tc-a1r",
        prompt="p", mode="chat", provider="claude",
    )
    db.refresh(req)
    service.mark_completed(req.id, {}, raw_response="some_output")
    db.refresh(req)
    assert req.status == "completed"
    assert req.raw_response == "some_output"


def test_chat_session_mark_completed_E_raises_no_typeerror_on_completion(service, db):
    """ERROR: result 인자 없이 호출 시 TypeError 발생 확인 (회귀 방지 — 수정 전 버그 재현)"""
    req = service.enqueue(
        caller_type="test", caller_id="tc-a1e",
        prompt="p", mode="chat", provider="claude",
    )
    db.refresh(req)
    # 수정 후: result={}를 전달해야 TypeError 없음
    service.mark_completed(req.id, {}, raw_response="ok")
    db.refresh(req)
    assert req.status == "completed"


def test_chat_session_mark_failed_E_on_nonzero_exit_code_raw_response_preserved(service, db):
    """ERROR: exit_code != 0 경로에서 mark_failed가 raw_response를 보존하는지 검증"""
    req = service.enqueue(
        caller_type="test", caller_id="tc-a1fail",
        prompt="p", mode="chat", provider="claude",
    )
    db.refresh(req)
    service.mark_failed(req.id, error_message="exit_code=1", raw_response="some_output")
    db.refresh(req)
    assert req.status == "failed"
    assert req.raw_response == "some_output"
    assert req.error_message == "exit_code=1"


def test_chat_session_mark_failed_E_on_exception_default_empty_raw_response(service, db):
    """ERROR: 예외 경로에서 mark_failed(raw_response='') 명시 전달 시 정상 처리"""
    req = service.enqueue(
        caller_type="test", caller_id="tc-a1exc",
        prompt="p", mode="chat", provider="claude",
    )
    db.refresh(req)
    service.mark_failed(req.id, error_message="RuntimeError", raw_response="")
    db.refresh(req)
    assert req.status == "failed"
    assert req.error_message == "RuntimeError"


# ========== TC 22: _extract_last_json 정상 JSON 추출 ==========

def test_extract_last_json_right():
    lines = ["log line", '{"success":true,"moved":[]}', ""]
    result = _extract_last_json(lines)
    assert result == '{"success":true,"moved":[]}'


# ========== TC 23: JSON 없을 때 None 반환 ==========

def test_extract_last_json_boundary_no_json():
    result = _extract_last_json(["just log", "more log"])
    assert result is None


# ========== TC 24: 깨진 JSON 건너뜀 ==========

def test_extract_last_json_error_invalid():
    lines = ["{invalid}", '{"ok":true}']
    result = _extract_last_json(lines)
    assert result == '{"ok":true}'


# ========== TC 25: mode 분기 정확성 ==========

@pytest.mark.asyncio
async def test_process_pending_mode_routing_right(service, db):
    from app.modules.claude_worker.worker.worker import LLMWorker

    worker = LLMWorker.__new__(LLMWorker)
    worker._update_worker_state = MagicMock()
    worker._delegate_to_chat_executor = AsyncMock()
    worker._execute_request = AsyncMock()

    # chat 요청 → _delegate_to_chat_executor 호출, _execute_request 미호출
    req_chat = LLMRequest(
        caller_type="test", caller_id="tc25-chat",
        prompt="p", mode="chat", provider="claude", queue_name="utility",
    )
    db.add(req_chat)
    db.commit()

    with patch.object(LLMService, "get_next_request", return_value=req_chat), \
         patch.object(LLMService, "get_provider_quota_pause", return_value=None), \
         patch.object(LLMService, "get_blocked_pending_count", return_value=0):
        await worker._process_pending_requests()

    worker._delegate_to_chat_executor.assert_called_once()
    worker._execute_request.assert_not_called()

    # 초기화 후 single 요청 → _execute_request 호출, _delegate 미호출
    worker._delegate_to_chat_executor.reset_mock()
    worker._execute_request.reset_mock()

    req_single = LLMRequest(
        caller_type="test", caller_id="tc25-single",
        prompt="p", mode="single", provider="claude", queue_name="utility",
    )
    db.add(req_single)
    db.commit()

    with patch.object(LLMService, "get_next_request", return_value=req_single), \
         patch.object(LLMService, "get_provider_quota_pause", return_value=None), \
         patch.object(LLMService, "get_blocked_pending_count", return_value=0):
        await worker._process_pending_requests()

    worker._delegate_to_chat_executor.assert_not_called()
    worker._execute_request.assert_called_once()

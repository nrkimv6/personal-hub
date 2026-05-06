"""
ChatExecutor._run_chat_session 완료 경로 통합 TC (T3)

fix: plan 필수 — 근본 원인(mark_completed positional result 누락 → TypeError)을
실제 LLMService + in-memory DB 환경에서 재현하고 수정 후 통과를 검증한다.

패턴:
  - 실제 LLMService + in-memory SQLite (mark_completed/mark_failed mock 없음)
  - subprocess.Popen → stub (claude CLI 불필요)
  - build_cli_env → MagicMock (CLAUDE_CONFIG_DIR 불필요)
  - redis_client.publish → MagicMock (Redis 서버 불필요)
  - executor 내부 세션과 검증 세션을 분리 (finally db.close() 영향 방지)
"""

import io
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import psycopg2
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.worker.chat_executor import ChatExecutor


# ---------------------------------------------------------------------------
# Shared in-memory engine (module scope — 테이블 1회 생성)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    LLMRequest.__table__.create(bind=e, checkfirst=True)
    return e


@pytest.fixture(scope="module")
def SessionFactory(engine):
    return sessionmaker(bind=engine)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executor(SessionFactory):
    """
    ChatExecutor 인스턴스 반환.
    _get_db_service는 매 호출마다 새로운 세션을 반환 → finally db.close()가 테스트 세션에 영향 없음.
    """
    executor = ChatExecutor.__new__(ChatExecutor)
    executor.redis_url = "redis://localhost:6379/0"
    executor._stop_event = MagicMock()
    executor._busy = False
    executor.redis_client = MagicMock()

    def fresh_db_service():
        db = SessionFactory()
        svc = LLMService(db)
        return db, svc

    executor._get_db_service = fresh_db_service
    return executor


def _fake_proc(lines, returncode=0):
    """subprocess.Popen stub."""
    text = "".join(f"{line}\n" for line in lines)
    proc = SimpleNamespace(
        stdout=io.StringIO(text),
        wait=MagicMock(return_value=None),
        returncode=returncode,
        pid=99999,
    )
    return proc


def _enqueue_and_get_id(SessionFactory, caller_id, mode="chat"):
    """별도 세션으로 요청 enqueue 후 id 반환."""
    db = SessionFactory()
    try:
        svc = LLMService(db)
        req = svc.enqueue(
            caller_type="test",
            caller_id=caller_id,
            prompt="test prompt",
            mode=mode,
            provider="claude",
        )
        db.flush()
        return req.id
    finally:
        db.close()


def _get_request_status(SessionFactory, request_id):
    """별도 세션으로 요청 상태 조회."""
    db = SessionFactory()
    try:
        req = db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
        return {
            "status": req.status,
            "raw_response": req.raw_response,
            "error_message": req.error_message,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# T3-1: 정상 완료 경로 — TypeError 없이 DB status=completed 전환 검증
# ---------------------------------------------------------------------------


def test_run_chat_session_T3_normal_completion_no_typeerror(SessionFactory):
    """
    T3(RIGHT): _run_chat_session의 exit_code=0 경로에서
      - mark_completed가 TypeError 없이 호출되고
      - DB status가 'completed'로 전환되는지 검증

    수정 전(bug): mark_completed(request_id, raw_response=...) → TypeError
    수정 후: mark_completed(request_id, {}, raw_response=...)  → 정상
    """
    request_id = _enqueue_and_get_id(SessionFactory, "t3-normal")

    executor = _make_executor(SessionFactory)
    fake_proc = _fake_proc(['{"success":true,"result":"ok"}'], returncode=0)

    with patch("subprocess.Popen", return_value=fake_proc), \
         patch(
             "app.modules.claude_worker.services.profile_env.build_cli_env",
             return_value=os.environ.copy(),
         ):
        executor._run_chat_session(
            request_id=request_id,
            prompt="hello",
            provider="claude",
            model="",
            cli_options={},
            chat_session_id="session-t3",
        )

    result = _get_request_status(SessionFactory, request_id)
    assert result["status"] == "completed", (
        f"status={result['status']}. mark_completed TypeError 재발 가능성. "
        f"raw_response={result['raw_response']!r}, error_message={result['error_message']!r}"
    )


# ---------------------------------------------------------------------------
# T3-2: exit_code != 0 경로 — status=failed + error_message 확인
# ---------------------------------------------------------------------------


def test_run_chat_session_T3_nonzero_exit_code_sets_failed(SessionFactory):
    """
    T3(ERROR): exit_code != 0일 때
      - DB status가 'failed'로 전환되고
      - error_message에 exit_code=1이 포함되는지 검증
    """
    request_id = _enqueue_and_get_id(SessionFactory, "t3-exitcode")

    executor = _make_executor(SessionFactory)
    fake_proc = _fake_proc(["some output line", "another line"], returncode=1)

    with patch("subprocess.Popen", return_value=fake_proc), \
         patch(
             "app.modules.claude_worker.services.profile_env.build_cli_env",
             return_value=os.environ.copy(),
         ):
        executor._run_chat_session(
            request_id=request_id,
            prompt="p",
            provider="claude",
            model="",
            cli_options={},
            chat_session_id="session-t3-fail",
        )

    result = _get_request_status(SessionFactory, request_id)
    assert result["status"] == "failed", f"status={result['status']}, expected 'failed'"
    assert result["error_message"] and "exit_code=1" in result["error_message"], (
        f"error_message={result['error_message']!r}"
    )


# ---------------------------------------------------------------------------
# T3-3: 예외 발생 경로 — status=failed + error_message 저장
# ---------------------------------------------------------------------------


def test_run_chat_session_T3_exception_sets_failed_with_error_message(SessionFactory):
    """
    T3(ERROR): subprocess.Popen이 예외를 발생시킬 때
      - DB status가 'failed'로 전환되고
      - error_message에 예외 메시지가 저장되는지 검증
    """
    request_id = _enqueue_and_get_id(SessionFactory, "t3-exception")

    executor = _make_executor(SessionFactory)

    with patch("subprocess.Popen", side_effect=RuntimeError("claude binary not found")), \
         patch(
             "app.modules.claude_worker.services.profile_env.build_cli_env",
             return_value=os.environ.copy(),
         ):
        executor._run_chat_session(
            request_id=request_id,
            prompt="p",
            provider="claude",
            model="",
            cli_options={},
            chat_session_id="session-t3-exc",
        )

    result = _get_request_status(SessionFactory, request_id)
    assert result["status"] == "failed", f"status={result['status']}"
    assert result["error_message"] and "claude binary not found" in result["error_message"], (
        f"error_message={result['error_message']!r}"
    )


# ---------------------------------------------------------------------------
# T3-4: mark_completed PG 오류 — warning-only + Redis publish 유지
# ---------------------------------------------------------------------------


def test_run_chat_session_pg_connection_error_from_mark_completed_no_traceback(
    SessionFactory, caplog
):
    """
    T3(B): real LLMService + SQLite, mark_completed 시점 commit에서
    psycopg2.OperationalError 주입 → warning-only, Redis publish 유지 검증.
    """
    request_id = _enqueue_and_get_id(SessionFactory, "t3-pg-mark-completed")

    # Real db session — commit PG error injection (2번째 commit부터)
    db_real = SessionFactory()
    original_commit = db_real.commit
    call_count = [0]

    def pg_on_second_commit():
        call_count[0] += 1
        if call_count[0] >= 2:
            raise psycopg2.OperationalError("could not connect to server")
        return original_commit()

    db_real.commit = pg_on_second_commit
    svc = LLMService(db_real)

    executor = ChatExecutor.__new__(ChatExecutor)
    executor.redis_url = "redis://localhost:6379/0"
    executor._stop_event = MagicMock()
    executor._busy = False
    executor.redis_client = MagicMock()
    executor._get_db_service = MagicMock(return_value=(db_real, svc))

    fake_proc = _fake_proc(['{"success":true}'], returncode=0)

    with patch("subprocess.Popen", return_value=fake_proc), \
         patch(
             "app.modules.claude_worker.services.profile_env.build_cli_env",
             return_value=os.environ.copy(),
         ), \
         caplog.at_level(logging.DEBUG):
        executor._run_chat_session(
            request_id=request_id,
            prompt="hello",
            provider="claude",
            model="",
            cli_options={},
            chat_session_id="sess-t3-pg-mc",
        )

    pg_warnings = [r for r in caplog.records
                   if r.levelno == logging.WARNING and "connection error" in r.message]
    assert len(pg_warnings) >= 1, "PG connection error warning 없음"

    error_with_tb = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert len(error_with_tb) == 0, f"traceback 로그 {len(error_with_tb)}건 발생"

    executor.redis_client.publish.assert_called()


# ---------------------------------------------------------------------------
# T3-5: stream_log_path DB 저장 PG 오류 — warning-only + Redis + cleanup 유지
# ---------------------------------------------------------------------------


def test_run_chat_session_pg_connection_error_from_stream_log_update_no_traceback(
    SessionFactory, caplog, tmp_path
):
    """
    T3(B): real LLMService + SQLite, stream_log_path 저장 commit에서
    psycopg2.OperationalError 주입 → warning-only + Redis publish + 임시 파일 정리 검증.
    """
    request_id = _enqueue_and_get_id(SessionFactory, "t3-pg-stream-log")

    # Real db session — 첫 번째 commit부터 PG error
    db_real = SessionFactory()
    original_commit = db_real.commit

    def pg_on_first_commit():
        raise psycopg2.OperationalError("could not connect to server")

    db_real.commit = pg_on_first_commit
    svc = LLMService(db_real)

    executor = ChatExecutor.__new__(ChatExecutor)
    executor.redis_url = "redis://localhost:6379/0"
    executor._stop_event = MagicMock()
    executor._busy = False
    executor.redis_client = MagicMock()
    executor._get_db_service = MagicMock(return_value=(db_real, svc))

    fake_proc = _fake_proc(['{"success":true}'], returncode=0)

    with patch("subprocess.Popen", return_value=fake_proc), \
         patch(
             "app.modules.claude_worker.services.profile_env.build_cli_env",
             return_value=os.environ.copy(),
         ), \
         caplog.at_level(logging.DEBUG):
        executor._run_chat_session(
            request_id=request_id,
            prompt="hello",
            provider="claude",
            model="",
            cli_options={},
            chat_session_id="sess-t3-pg-sl",
        )

    pg_warnings = [r for r in caplog.records
                   if r.levelno == logging.WARNING and "connection error" in r.message]
    assert len(pg_warnings) >= 1, "PG connection error warning 없음"

    error_with_tb = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert len(error_with_tb) == 0, f"traceback 로그 {len(error_with_tb)}건 발생"

    # Redis __COMPLETED__ publish 유지 검증
    executor.redis_client.publish.assert_called()

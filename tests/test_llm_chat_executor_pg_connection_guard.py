"""
test_llm_chat_executor_pg_connection_guard.py — ChatExecutor PG guard TC

B/E: PG 연결 오류 발생 경로에서 warning 1회만 기록, traceback 없음
R: subprocess/runtime 비DB 오류는 exc_info=True 유지

수정 대상: _run_chat_session() outer except Exception 블록
  - is_connection_error(e) → logger.warning (traceback 억제)
  - else → logger.error(..., exc_info=True) 유지
  - 양쪽 모두 service.mark_failed, Redis __COMPLETED__, prompt cleanup 유지
"""
import io
import logging
import os
import psycopg2
import sqlalchemy.exc
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.modules.claude_worker.worker.chat_executor import ChatExecutor


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _make_executor():
    """DB/redis를 mock으로 대체한 ChatExecutor 인스턴스."""
    executor = ChatExecutor.__new__(ChatExecutor)
    executor.redis_url = "redis://localhost:6379/0"
    executor._stop_event = MagicMock()
    executor._busy = False
    executor.redis_client = MagicMock()
    return executor


def _fake_proc(lines=None, returncode=0):
    """subprocess.Popen stub — stdout에 lines를 출력하고 returncode 반환."""
    text = "".join(f"{line}\n" for line in (lines or ['{"success":true}']))
    proc = SimpleNamespace(
        stdout=io.StringIO(text),
        wait=MagicMock(return_value=None),
        returncode=returncode,
        pid=88888,
    )
    return proc


def _make_db_service(commit_error=None, mark_completed_error=None):
    """(db, service) mock 쌍 반환."""
    db = MagicMock()
    service = MagicMock()
    if commit_error:
        db.commit.side_effect = commit_error
    if mark_completed_error:
        service.mark_completed.side_effect = mark_completed_error
    return db, service


# ─────────────────────────────────────────────────────────────
# B: PG 연결 오류 시 warning 1회, traceback 없음
# ─────────────────────────────────────────────────────────────

def test_run_chat_session_stream_log_commit_pg_error_no_traceback(caplog, tmp_path):
    """B: stream_log_path commit 시 psycopg2.OperationalError → warning 1회, traceback 없음."""
    pg_err = psycopg2.OperationalError("could not connect to server")
    db, service = _make_db_service(commit_error=pg_err)
    executor = _make_executor()
    executor._get_db_service = MagicMock(return_value=(db, service))

    fake_proc = _fake_proc(['{"success":true}'], returncode=0)

    with patch("subprocess.Popen", return_value=fake_proc), \
         patch("app.modules.claude_worker.services.profile_env.build_cli_env",
               return_value=dict(os.environ)), \
         caplog.at_level(logging.DEBUG):
        executor._run_chat_session(
            request_id=999,
            prompt="hello",
            provider="claude",
            model="claude-sonnet-4-6",
            cli_options={},
            chat_session_id="sess-test",
        )

    pg_warnings = [r for r in caplog.records
                   if r.levelno == logging.WARNING and "connection error" in r.message]
    assert len(pg_warnings) >= 1
    error_with_traceback = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert len(error_with_traceback) == 0
    executor.redis_client.publish.assert_called()


def test_run_chat_session_mark_completed_pg_error_no_traceback(caplog):
    """B: service.mark_completed PG 실패 → warning 1회, traceback 없음, Redis publish 유지."""
    pg_err = psycopg2.OperationalError("could not connect to server")
    db, service = _make_db_service(mark_completed_error=pg_err)
    executor = _make_executor()
    executor._get_db_service = MagicMock(return_value=(db, service))

    fake_proc = _fake_proc(['{"success":true}'], returncode=0)

    with patch("subprocess.Popen", return_value=fake_proc), \
         patch("app.modules.claude_worker.services.profile_env.build_cli_env",
               return_value=dict(os.environ)), \
         caplog.at_level(logging.DEBUG):
        executor._run_chat_session(
            request_id=1001,
            prompt="hello",
            provider="claude",
            model="claude-sonnet-4-6",
            cli_options={},
            chat_session_id="sess-test-2",
        )

    pg_warnings = [r for r in caplog.records
                   if r.levelno == logging.WARNING and "connection error" in r.message]
    assert len(pg_warnings) >= 1
    error_with_traceback = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert len(error_with_traceback) == 0
    executor.redis_client.publish.assert_called()


def test_run_chat_session_non_pg_error_preserves_exc_info(caplog):
    """R: subprocess.Popen RuntimeError(비DB) → logger.error exc_info=True 유지."""
    db, service = _make_db_service()
    executor = _make_executor()
    executor._get_db_service = MagicMock(return_value=(db, service))

    with patch("subprocess.Popen", side_effect=RuntimeError("unexpected subprocess error")), \
         patch("app.modules.claude_worker.services.profile_env.build_cli_env",
               return_value=dict(os.environ)), \
         caplog.at_level(logging.DEBUG):
        executor._run_chat_session(
            request_id=1002,
            prompt="hello",
            provider="claude",
            model="claude-sonnet-4-6",
            cli_options={},
            chat_session_id="sess-test-3",
        )

    error_with_traceback = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert len(error_with_traceback) >= 1
    pg_warnings = [r for r in caplog.records if "connection error" in r.message]
    assert len(pg_warnings) == 0
    executor.redis_client.publish.assert_called()

"""
writing_callback_handler.py is_connection_error guard TC

RIGHT-BICEP: R(Right), E(Error), B(Boundary)
T1 + T3: T1 uses mock is_connection_error; T3 uses real psycopg2/SQLAlchemy exceptions.

Note: WritingCallbackHandler is a dormant callback path (0 live call-sites as of 2026-04-24).
      These are preventive guard tests.
"""

import pytest
import sqlalchemy.exc
from unittest.mock import MagicMock, patch, call

from app.modules.writing.services.writing_callback_handler import WritingCallbackHandler

try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


def _make_handler():
    db = MagicMock()
    return WritingCallbackHandler(db), db


def _make_request(writing_batch_id=1):
    req = MagicMock()
    req.writing_batch_id = writing_batch_id
    req.id = 42
    req.writing_metadata = None  # _parse_metadata가 MagicMock을 json.loads에 전달하지 않도록
    return req


def _make_llm_result():
    return {"content": "generated text"}


# ---------------------------------------------------------------------------
# R: Right — PG 연결 오류 시 warning + sentinel return + rollback
# ---------------------------------------------------------------------------

def test_handle_success_pg_error_returns_none_right():
    """R: handle_success db.commit() PG 오류 시 warning + None 반환 + rollback"""
    handler, db = _make_handler()
    db.commit.side_effect = RuntimeError("connection refused")

    req = _make_request()
    with patch("app.modules.writing.services.writing_callback_handler.is_connection_error", return_value=True), \
         patch("app.modules.writing.services.writing_callback_handler.logger") as mock_log:
        result = handler.handle_success(req, _make_llm_result(), "raw text")

    assert result is None
    db.rollback.assert_called_once()
    mock_log.warning.assert_called_once()
    assert not mock_log.error.called


def test_handle_failure_pg_error_returns_false_right():
    """R: handle_failure db.commit() PG 오류 시 warning + False 반환 + rollback"""
    handler, db = _make_handler()
    db.commit.side_effect = RuntimeError("connection refused")

    req = _make_request()
    with patch("app.modules.writing.services.writing_callback_handler.is_connection_error", return_value=True), \
         patch("app.modules.writing.services.writing_callback_handler.logger") as mock_log:
        result = handler.handle_failure(req, "some llm error")

    assert result is False
    db.rollback.assert_called_once()
    mock_log.warning.assert_called_once()
    assert not mock_log.error.called


# ---------------------------------------------------------------------------
# E: Error — 비PG 예외는 error+exc_info 유지
# ---------------------------------------------------------------------------

def test_handle_success_non_pg_error_keeps_traceback_error():
    """E: handle_success 일반 예외 시 error+exc_info 유지 + None 반환"""
    handler, db = _make_handler()
    db.commit.side_effect = ValueError("integrity constraint")

    req = _make_request()
    with patch("app.modules.writing.services.writing_callback_handler.is_connection_error", return_value=False), \
         patch("app.modules.writing.services.writing_callback_handler.logger") as mock_log:
        result = handler.handle_success(req, _make_llm_result(), "raw text")

    assert result is None
    db.rollback.assert_called_once()
    mock_log.error.assert_called_once()
    call_kwargs = mock_log.error.call_args[1]
    assert call_kwargs.get("exc_info") is True
    assert not mock_log.warning.called


def test_handle_failure_non_pg_error_keeps_traceback_error():
    """E: handle_failure 일반 예외 시 error+exc_info 유지 + False 반환"""
    handler, db = _make_handler()
    db.commit.side_effect = ValueError("integrity constraint")

    req = _make_request()
    with patch("app.modules.writing.services.writing_callback_handler.is_connection_error", return_value=False), \
         patch("app.modules.writing.services.writing_callback_handler.logger") as mock_log:
        result = handler.handle_failure(req, "some llm error")

    assert result is False
    db.rollback.assert_called_once()
    mock_log.error.assert_called_once()
    call_kwargs = mock_log.error.call_args[1]
    assert call_kwargs.get("exc_info") is True
    assert not mock_log.warning.called


# ---------------------------------------------------------------------------
# B: Boundary — non-connection OperationalError는 error+traceback 유지
# ---------------------------------------------------------------------------

def test_handle_success_pg_non_connection_error_keeps_traceback_boundary():
    """B: non-connection OperationalError success path — error+traceback + None 반환"""
    handler, db = _make_handler()
    db.commit.side_effect = RuntimeError("deadlock detected")

    req = _make_request()
    with patch("app.modules.writing.services.writing_callback_handler.is_connection_error", return_value=False), \
         patch("app.modules.writing.services.writing_callback_handler.logger") as mock_log:
        result = handler.handle_success(req, _make_llm_result(), "raw text")

    assert result is None
    db.rollback.assert_called_once()
    mock_log.error.assert_called_once()
    call_kwargs = mock_log.error.call_args[1]
    assert call_kwargs.get("exc_info") is True
    assert not mock_log.warning.called


def test_handle_failure_pg_non_connection_error_keeps_traceback_boundary():
    """B: non-connection OperationalError failure path — error+traceback + False 반환"""
    handler, db = _make_handler()
    db.commit.side_effect = RuntimeError("deadlock detected")

    req = _make_request()
    with patch("app.modules.writing.services.writing_callback_handler.is_connection_error", return_value=False), \
         patch("app.modules.writing.services.writing_callback_handler.logger") as mock_log:
        result = handler.handle_failure(req, "some llm error")

    assert result is False
    db.rollback.assert_called_once()
    mock_log.error.assert_called_once()
    call_kwargs = mock_log.error.call_args[1]
    assert call_kwargs.get("exc_info") is True
    assert not mock_log.warning.called


# ---------------------------------------------------------------------------
# T3: 실물 psycopg2 / SQLAlchemy 예외 객체로 재현
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_PSYCOPG2, reason="psycopg2 not installed")
def test_handle_success_real_psycopg2_connection_refused_t3():
    """T3: 실물 psycopg2.OperationalError handle_success — warning + None 반환"""
    handler, db = _make_handler()
    db.commit.side_effect = psycopg2.OperationalError("connection refused")

    req = _make_request()
    with patch("app.modules.writing.services.writing_callback_handler.logger") as mock_log:
        result = handler.handle_success(req, _make_llm_result(), "raw text")

    assert result is None
    db.rollback.assert_called_once()
    mock_log.warning.assert_called_once()
    assert not mock_log.error.called


@pytest.mark.skipif(not HAS_PSYCOPG2, reason="psycopg2 not installed")
def test_handle_failure_real_psycopg2_connection_refused_t3():
    """T3: 실물 psycopg2.OperationalError handle_failure — warning + False 반환"""
    handler, db = _make_handler()
    db.commit.side_effect = psycopg2.OperationalError("server closed the connection unexpectedly")

    req = _make_request()
    with patch("app.modules.writing.services.writing_callback_handler.logger") as mock_log:
        result = handler.handle_failure(req, "some llm error")

    assert result is False
    db.rollback.assert_called_once()
    mock_log.warning.assert_called_once()
    assert not mock_log.error.called


@pytest.mark.skipif(not HAS_PSYCOPG2, reason="psycopg2 not installed")
def test_handle_success_real_sqlalchemy_operational_t3():
    """T3: 실물 SQLAlchemy OperationalError(orig=psycopg2) handle_success — warning + None 반환"""
    handler, db = _make_handler()
    orig = psycopg2.OperationalError("could not connect to server")
    sa_exc = sqlalchemy.exc.OperationalError("stmt", {}, orig)
    db.commit.side_effect = sa_exc

    req = _make_request()
    with patch("app.modules.writing.services.writing_callback_handler.logger") as mock_log:
        result = handler.handle_success(req, _make_llm_result(), "raw text")

    assert result is None
    db.rollback.assert_called_once()
    mock_log.warning.assert_called_once()
    assert not mock_log.error.called

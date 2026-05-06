"""
proxy_usage_logger.py _batch_insert_logs is_connection_error guard TC

RIGHT-BICEP: R(Right), E(Error), B(Boundary)
T1 + T3: T1 uses mock is_connection_error; T3 uses real psycopg2/SQLAlchemy exceptions.
"""

import pytest
import sqlalchemy.exc
from unittest.mock import MagicMock, patch, call

from app.services.proxy_usage_logger import ProxyUsageLogger

try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


def _sample_entries():
    from datetime import datetime
    return [{
        "schedule_id": 1,
        "monitoring_event_id": None,
        "proxy_url": "http://1.2.3.4:8080",
        "proxy_host": "1.2.3.4",
        "request_id": "test-req-id",
        "attempt_number": 1,
        "success": True,
        "http_status": 200,
        "error_type": None,
        "error_message": None,
        "response_time_ms": 500,
        "target_url": "https://example.com",
        "fetch_method": "graphql_api",
        "http_method": "get",
        "timestamp": datetime.now(),
    }]


def _make_session_mock(commit_side_effect):
    session = MagicMock()
    session.commit.side_effect = commit_side_effect
    return session


# ---------------------------------------------------------------------------
# R: Right — PG 연결 오류 시 rollback + warning + re-raise
# ---------------------------------------------------------------------------

def test_batch_insert_pg_error_no_traceback_right():
    """R: _batch_insert_logs PG 연결 오류 시 rollback + warning + re-raise"""
    logger_inst = ProxyUsageLogger()
    session = _make_session_mock(RuntimeError("connection refused"))

    with patch("app.services.proxy_usage_logger.is_connection_error", return_value=True), \
         patch("app.services.proxy_usage_logger.logger") as mock_log, \
         patch("app.database.SessionLocal", return_value=session), \
         patch("app.models.proxy_usage.ProxyUsageLog", MagicMock):
        with pytest.raises(RuntimeError, match="connection refused"):
            logger_inst._batch_insert_logs(_sample_entries())

    session.rollback.assert_called_once()
    mock_log.warning.assert_called_once()
    assert not mock_log.error.called


# ---------------------------------------------------------------------------
# E: Error — 비PG 예외는 rollback + error+exc_info + re-raise
# ---------------------------------------------------------------------------

def test_batch_insert_non_pg_error_keeps_traceback_error():
    """E: 일반 예외는 error+exc_info 유지 + re-raise"""
    logger_inst = ProxyUsageLogger()
    session = _make_session_mock(ValueError("constraint violation"))

    with patch("app.services.proxy_usage_logger.is_connection_error", return_value=False), \
         patch("app.services.proxy_usage_logger.logger") as mock_log, \
         patch("app.database.SessionLocal", return_value=session), \
         patch("app.models.proxy_usage.ProxyUsageLog", MagicMock):
        with pytest.raises(ValueError, match="constraint violation"):
            logger_inst._batch_insert_logs(_sample_entries())

    session.rollback.assert_called_once()
    mock_log.error.assert_called_once()
    call_kwargs = mock_log.error.call_args[1]
    assert call_kwargs.get("exc_info") is True
    assert not mock_log.warning.called


# ---------------------------------------------------------------------------
# B: Boundary — non-connection OperationalError는 error+traceback + re-raise
# ---------------------------------------------------------------------------

def test_batch_insert_pg_operational_non_connection_keeps_traceback_boundary():
    """B: non-connection OperationalError는 error+traceback + re-raise"""
    logger_inst = ProxyUsageLogger()
    session = _make_session_mock(RuntimeError("table proxy_usage_log does not exist"))

    with patch("app.services.proxy_usage_logger.is_connection_error", return_value=False), \
         patch("app.services.proxy_usage_logger.logger") as mock_log, \
         patch("app.database.SessionLocal", return_value=session), \
         patch("app.models.proxy_usage.ProxyUsageLog", MagicMock):
        with pytest.raises(RuntimeError):
            logger_inst._batch_insert_logs(_sample_entries())

    session.rollback.assert_called_once()
    mock_log.error.assert_called_once()
    call_kwargs = mock_log.error.call_args[1]
    assert call_kwargs.get("exc_info") is True
    assert not mock_log.warning.called


# ---------------------------------------------------------------------------
# T3: 실물 psycopg2 / SQLAlchemy 예외 객체로 재현
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_PSYCOPG2, reason="psycopg2 not installed")
def test_batch_insert_real_psycopg2_connection_refused_t3():
    """T3: 실물 psycopg2.OperationalError — warning + rollback + re-raise"""
    logger_inst = ProxyUsageLogger()
    exc = psycopg2.OperationalError("connection refused")
    session = _make_session_mock(exc)

    with patch("app.services.proxy_usage_logger.logger") as mock_log, \
         patch("app.database.SessionLocal", return_value=session), \
         patch("app.models.proxy_usage.ProxyUsageLog", MagicMock):
        with pytest.raises(psycopg2.OperationalError):
            logger_inst._batch_insert_logs(_sample_entries())

    session.rollback.assert_called_once()
    mock_log.warning.assert_called_once()
    assert not mock_log.error.called


@pytest.mark.skipif(not HAS_PSYCOPG2, reason="psycopg2 not installed")
def test_batch_insert_real_sqlalchemy_operational_connection_refused_t3():
    """T3: 실물 SQLAlchemy OperationalError(orig=psycopg2) — warning + rollback + re-raise"""
    logger_inst = ProxyUsageLogger()
    orig = psycopg2.OperationalError("server closed the connection unexpectedly")
    sa_exc = sqlalchemy.exc.OperationalError("stmt", {}, orig)
    session = _make_session_mock(sa_exc)

    with patch("app.services.proxy_usage_logger.logger") as mock_log, \
         patch("app.database.SessionLocal", return_value=session), \
         patch("app.models.proxy_usage.ProxyUsageLog", MagicMock):
        with pytest.raises(sqlalchemy.exc.OperationalError):
            logger_inst._batch_insert_logs(_sample_entries())

    session.rollback.assert_called_once()
    mock_log.warning.assert_called_once()
    assert not mock_log.error.called

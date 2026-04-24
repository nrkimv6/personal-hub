"""
async_db_writer.py is_connection_error guard TC

RIGHT-BICEP: R(Right), E(Error), B(Boundary)
T1 + T3: T1 uses mock is_connection_error; T3 uses real psycopg2/SQLAlchemy exceptions.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy.exc

from app.utils.async_db_writer import AsyncDBWriter, DBOperation

try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


def _make_op(fn=None):
    if fn is None:
        fn = lambda: None  # noqa: E731
    return DBOperation(operation=fn, args=(), kwargs={}, created_at=datetime.now())


# ---------------------------------------------------------------------------
# R: Right — 정상 PG 연결 오류 시 warning만, exc_info 없음
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_loop_pg_error_no_traceback_right():
    """R: _process_loop outer except — PG 연결 오류 시 warning만 기록"""
    # batch_size(10)개를 채워 wait_for timeout 불필요, asyncio.sleep 패치로 즉시 반환
    writer = AsyncDBWriter(name="test-writer")
    writer._running = True

    async def mock_execute(batch):
        writer._running = False
        raise RuntimeError("connection refused")

    for _ in range(writer.batch_size):
        await writer.queue.put(_make_op())

    with patch("app.utils.async_db_writer.is_connection_error", return_value=True), \
         patch("app.utils.async_db_writer.logger") as mock_log, \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch.object(writer, "_execute_batch", side_effect=mock_execute):
        await writer._process_loop()

    mock_log.warning.assert_called_once()
    assert not mock_log.error.called


@pytest.mark.asyncio
async def test_execute_batch_pg_error_no_traceback_right():
    """R: _execute_batch — asyncio.to_thread PG 오류 시 warning만 기록"""
    writer = AsyncDBWriter("test-writer")
    op = _make_op()

    with patch("app.utils.async_db_writer.asyncio.to_thread",
               side_effect=RuntimeError("connection refused")), \
         patch("app.utils.async_db_writer.is_connection_error", return_value=True), \
         patch("app.utils.async_db_writer.logger") as mock_log:
        await writer._execute_batch([op])

    mock_log.warning.assert_called_once()
    assert not mock_log.error.called


def test_sync_execute_batch_pg_error_no_traceback_right():
    """R: _sync_execute_batch — op PG 오류 시 warning만, _failed_operations 카운트 유지"""
    writer = AsyncDBWriter("test-writer")

    def pg_fail():
        raise RuntimeError("connection refused")

    op = _make_op(pg_fail)

    with patch("app.utils.async_db_writer.is_connection_error", return_value=True), \
         patch("app.utils.async_db_writer.logger") as mock_log:
        writer._sync_execute_batch([op])

    assert writer._failed_operations == 1
    mock_log.warning.assert_called_once()
    assert not mock_log.error.called


# ---------------------------------------------------------------------------
# E: Error — 비PG 예외는 error + exc_info 유지
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_loop_non_pg_error_keeps_traceback_error():
    """E: _process_loop — 일반 예외는 error+exc_info 유지"""
    writer = AsyncDBWriter(name="test-writer")
    writer._running = True

    async def mock_execute(batch):
        writer._running = False
        raise ValueError("unexpected logic error")

    for _ in range(writer.batch_size):
        await writer.queue.put(_make_op())

    with patch("app.utils.async_db_writer.is_connection_error", return_value=False), \
         patch("app.utils.async_db_writer.logger") as mock_log, \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch.object(writer, "_execute_batch", side_effect=mock_execute):
        await writer._process_loop()

    mock_log.error.assert_called_once()
    call_kwargs = mock_log.error.call_args[1]
    assert call_kwargs.get("exc_info") is True
    assert not mock_log.warning.called


def test_sync_execute_batch_non_pg_error_keeps_traceback_error():
    """E: _sync_execute_batch — 일반 예외는 traceback 유지"""
    writer = AsyncDBWriter("test-writer")

    def fail():
        raise ValueError("unexpected")

    op = _make_op(fail)

    with patch("app.utils.async_db_writer.is_connection_error", return_value=False), \
         patch("app.utils.async_db_writer.logger") as mock_log:
        writer._sync_execute_batch([op])

    assert writer._failed_operations == 1
    mock_log.error.assert_called_once()
    call_kwargs = mock_log.error.call_args[1]
    assert call_kwargs.get("exc_info") is True
    assert not mock_log.warning.called


# ---------------------------------------------------------------------------
# B: Boundary — non-connection OperationalError는 error+traceback 유지
# ---------------------------------------------------------------------------

def test_sync_execute_batch_pg_operational_non_connection_keeps_traceback_boundary():
    """B: non-connection OperationalError는 error+traceback 유지"""
    writer = AsyncDBWriter("test-writer")

    def fail():
        raise RuntimeError("table not found")  # non-connection

    op = _make_op(fail)

    with patch("app.utils.async_db_writer.is_connection_error", return_value=False), \
         patch("app.utils.async_db_writer.logger") as mock_log:
        writer._sync_execute_batch([op])

    assert writer._failed_operations == 1
    mock_log.error.assert_called_once()
    call_kwargs = mock_log.error.call_args[1]
    assert call_kwargs.get("exc_info") is True
    assert not mock_log.warning.called


# ---------------------------------------------------------------------------
# T3: 실물 psycopg2 / SQLAlchemy 예외 객체로 재현
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_PSYCOPG2, reason="psycopg2 not installed")
def test_sync_execute_batch_real_psycopg2_connection_refused_t3():
    """T3: 실물 psycopg2.OperationalError("connection refused") — warning-only contract"""
    writer = AsyncDBWriter("test-writer")

    def fail():
        raise psycopg2.OperationalError("connection refused")

    op = _make_op(fail)

    with patch("app.utils.async_db_writer.logger") as mock_log:
        writer._sync_execute_batch([op])

    assert writer._failed_operations == 1
    mock_log.warning.assert_called_once()
    assert not mock_log.error.called


@pytest.mark.skipif(not HAS_PSYCOPG2, reason="psycopg2 not installed")
def test_sync_execute_batch_real_sqlalchemy_operational_connection_refused_t3():
    """T3: 실물 SQLAlchemy OperationalError(orig=psycopg2) — warning-only contract"""
    writer = AsyncDBWriter("test-writer")
    orig = psycopg2.OperationalError("connection refused")
    sa_exc = sqlalchemy.exc.OperationalError("stmt", {}, orig)

    def fail():
        raise sa_exc

    op = _make_op(fail)

    with patch("app.utils.async_db_writer.logger") as mock_log:
        writer._sync_execute_batch([op])

    assert writer._failed_operations == 1
    mock_log.warning.assert_called_once()
    assert not mock_log.error.called

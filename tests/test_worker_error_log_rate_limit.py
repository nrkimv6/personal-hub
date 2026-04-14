"""tests/test_worker_error_log_rate_limit.py

워커 에러 로그 rate-limit 단위 테스트 (Phase T1 - 항목 9)
"""
import time
from unittest.mock import patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_db_circuit():
    """각 테스트 전 db_circuit 싱글턴 상태 초기화."""
    from app.core.database import db_circuit, _CLOSED
    with db_circuit._lock:
        db_circuit._state = _CLOSED
        db_circuit._fail_count = 0
        db_circuit._last_fail_time = 0.0
    yield
    with db_circuit._lock:
        db_circuit._state = _CLOSED
        db_circuit._fail_count = 0
        db_circuit._last_fail_time = 0.0


class MinimalWorker:
    """_log_worker_error를 테스트하기 위한 최소 워커."""

    def __init__(self):
        self.name = "rate_limit_test_worker"
        self._error_log_rate = {}

    def _log_worker_error(self, task_desc, exc):
        from app.shared.worker.base_worker import BaseWorker
        BaseWorker._log_worker_error(self, task_desc, exc)


# ── rate-limit 테스트 ─────────────────────────────────────────────────────────

def test_log_worker_error_rate_limits_connection_error_right():
    """동일 task_desc로 connection error 100회 호출 → 30초 구간 내 1회만 warning."""
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 없음")

    worker = MinimalWorker()
    orig = psycopg2.OperationalError("connection refused")

    warning_calls = []
    with patch("app.shared.worker.base_worker.logger") as mock_logger:
        mock_logger.warning.side_effect = lambda *a, **kw: warning_calls.append(a)
        for _ in range(100):
            worker._log_worker_error("dispatch", orig)

    assert len(warning_calls) == 1, f"예상 1회, 실제 {len(warning_calls)}회"


def test_log_worker_error_resets_after_30s_cross():
    """30초 경과 후 동일 task_desc에서 다시 warning 허용."""
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 없음")

    worker = MinimalWorker()
    orig = psycopg2.OperationalError("connection refused")

    warning_calls = []
    with patch("app.shared.worker.base_worker.logger") as mock_logger:
        mock_logger.warning.side_effect = lambda *a, **kw: warning_calls.append(a)
        # 첫 호출
        worker._log_worker_error("dispatch", orig)
        # 30초 경과 시뮬레이션
        worker._error_log_rate["dispatch"] = time.monotonic() - 31.0
        # 두 번째 호출 (허용)
        worker._log_worker_error("dispatch", orig)

    assert len(warning_calls) == 2


def test_log_worker_error_different_tasks_independent_right():
    """다른 task_desc는 독립적인 rate-limit 카운터 사용."""
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 없음")

    worker = MinimalWorker()
    orig = psycopg2.OperationalError("connection refused")

    warning_calls = []
    with patch("app.shared.worker.base_worker.logger") as mock_logger:
        mock_logger.warning.side_effect = lambda *a, **kw: warning_calls.append(a)
        for _ in range(5):
            worker._log_worker_error("task_a", orig)
            worker._log_worker_error("task_b", orig)

    # 각 task_desc당 1회 = 총 2회
    assert len(warning_calls) == 2


def test_log_worker_error_keeps_full_traceback_for_other_errors_right():
    """비 connection 에러는 exc_info=True ERROR 로깅 유지."""
    worker = MinimalWorker()
    exc = ValueError("unexpected value")

    error_calls = []
    with patch("app.shared.worker.base_worker.logger") as mock_logger:
        def capture_error(*a, **kw):
            error_calls.append(kw)
        mock_logger.error.side_effect = capture_error
        worker._log_worker_error("some_task", exc)

    assert len(error_calls) == 1
    assert error_calls[0].get("exc_info") is True


def test_log_worker_error_no_traceback_for_connection_error_right():
    """connection error는 exc_info 없이 WARNING만."""
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 없음")

    worker = MinimalWorker()
    orig = psycopg2.OperationalError("connection refused")

    with patch("app.shared.worker.base_worker.logger") as mock_logger:
        worker._log_worker_error("dispatch", orig)
        # error가 호출되지 않아야 함
        mock_logger.error.assert_not_called()
        # warning이 1회 호출
        mock_logger.warning.assert_called_once()


def test_log_worker_error_sqlalchemy_wrapped_connection_error_right():
    """sqlalchemy.exc.OperationalError로 래핑된 connection error도 감지."""
    try:
        import psycopg2
        import sqlalchemy.exc
    except ImportError:
        pytest.skip("psycopg2 또는 sqlalchemy 없음")

    worker = MinimalWorker()
    orig = psycopg2.OperationalError("connection refused")
    wrapped = sqlalchemy.exc.OperationalError("stmt", {}, orig)

    warning_calls = []
    with patch("app.shared.worker.base_worker.logger") as mock_logger:
        mock_logger.warning.side_effect = lambda *a, **kw: warning_calls.append(a)
        worker._log_worker_error("dispatch", wrapped)

    assert len(warning_calls) == 1

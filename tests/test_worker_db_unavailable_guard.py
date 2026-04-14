"""tests/test_worker_db_unavailable_guard.py

BaseWorker DB 불가 backoff 가드 단위 테스트 (Phase T1 - 항목 8, 9b)
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Fake 워커 ─────────────────────────────────────────────────────────────────

class FakeWorker:
    """테스트용 최소 BaseWorker 파생 클래스."""

    def __init__(self):
        from app.shared.worker.base_worker import BaseWorker
        # BaseWorker의 필드들을 직접 초기화
        self.name = "test_worker"
        self.browser = None
        self.shutdown_event = asyncio.Event()
        self.pid = 1234
        self.start_time = None
        self.worker_id = None
        self._running = False
        self._last_heartbeat_time = 0
        from collections import defaultdict
        self._running_tasks = set()
        self._consecutive_errors = 0
        self._max_consecutive_errors = 10
        self._last_error = None
        self._task_error_counts = defaultdict(int)
        # DB 불가 backoff 필드
        self._last_db_unavailable_log_time = 0.0
        self._was_db_unavailable = False
        self._error_log_rate = {}
        # 이터레이션 호출 카운터
        self.iteration_count = 0

    def _get_loop_interval(self) -> float:
        return 0.01  # 빠른 테스트용

    async def _main_loop_iteration(self):
        self.iteration_count += 1

    def _update_heartbeat(self):
        pass

    def _cleanup_completed_tasks(self):
        pass

    async def _wait_for_next_cycle(self, interval: float):
        # 바로 반환 (테스트 속도)
        self.shutdown_event.set()  # 1 cycle 후 종료

    def _log_db_unavailable_once(self):
        from app.shared.worker.base_worker import BaseWorker
        BaseWorker._log_db_unavailable_once(self)

    def _log_worker_error(self, task_desc, exc):
        from app.shared.worker.base_worker import BaseWorker
        BaseWorker._log_worker_error(self, task_desc, exc)

    async def _main_loop(self):
        from app.shared.worker.base_worker import BaseWorker
        await BaseWorker._main_loop(self)


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


# ── backoff 가드 테스트 ────────────────────────────────────────────────────────

def test_worker_skips_iteration_when_circuit_open_right():
    """circuit OPEN 상태에서 _main_loop_iteration 호출 안 됨."""
    from app.core.database import db_circuit, _OPEN

    with db_circuit._lock:
        db_circuit._state = _OPEN
        db_circuit._fail_count = 3
        db_circuit._last_fail_time = time.monotonic()  # 쿨다운 아직 안 지남

    worker = FakeWorker()
    # _wait_for_next_cycle이 즉시 종료하도록 설정
    asyncio.run(worker._main_loop())

    assert worker.iteration_count == 0


def test_worker_resumes_on_db_recovery_right():
    """circuit CLOSED(복구) 상태에서 _main_loop_iteration 호출."""
    from app.core.database import db_circuit, _CLOSED

    with db_circuit._lock:
        db_circuit._state = _CLOSED
        db_circuit._fail_count = 0

    worker = FakeWorker()
    asyncio.run(worker._main_loop())

    assert worker.iteration_count >= 1


def test_worker_db_unavailable_log_rate_limit_right():
    """60회 연속 OPEN 루프에서 logger.warning 호출 ≤2회 (30초당 1회)."""
    from app.core.database import db_circuit, _OPEN
    import logging

    with db_circuit._lock:
        db_circuit._state = _OPEN
        db_circuit._fail_count = 3
        db_circuit._last_fail_time = time.monotonic()

    worker = FakeWorker()
    worker._last_db_unavailable_log_time = 0.0  # 첫 호출 허용

    warning_calls = []

    with patch("app.shared.worker.base_worker.logger") as mock_logger:
        mock_logger.warning.side_effect = lambda *a, **kw: warning_calls.append(a)
        # 60회 _log_db_unavailable_once 호출 시뮬레이션
        for _ in range(60):
            worker._log_db_unavailable_once()

    # 30초 구간에서 1회만 허용 (첫 호출 시각 이후 30초 미경과이므로 1회)
    assert len(warning_calls) <= 2


def test_worker_consecutive_errors_not_incremented_on_db_guard_right():
    """DB 불가 backoff 루프에서 _consecutive_errors 증가 안 됨."""
    from app.core.database import db_circuit, _OPEN

    with db_circuit._lock:
        db_circuit._state = _OPEN
        db_circuit._fail_count = 3
        db_circuit._last_fail_time = time.monotonic()

    worker = FakeWorker()
    asyncio.run(worker._main_loop())

    assert worker._consecutive_errors == 0


def test_worker_logs_recovery_info_once_on_db_resume_right():
    """DB 복구 전환 시 '접근 재개' INFO 로그 정확히 1회만 호출."""
    from app.core.database import db_circuit, _CLOSED

    # DB 불가 → 복구 상태 설정
    worker = FakeWorker()
    worker._was_db_unavailable = True  # 이전에 불가 상태였음

    with db_circuit._lock:
        db_circuit._state = _CLOSED

    info_calls = []
    with patch("app.shared.worker.base_worker.logger") as mock_logger:
        mock_logger.info.side_effect = lambda *a, **kw: info_calls.append(a)
        asyncio.run(worker._main_loop())

    # "DB 접근 재개" 포함 로그 1회
    recovery_logs = [c for c in info_calls if "접근 재개" in str(c)]
    assert len(recovery_logs) == 1


# ── _log_worker_error rate-limit ──────────────────────────────────────────────

def test_log_worker_error_rate_limits_connection_error_right():
    """동일 task_desc로 connection error 100회 호출 시 30초 구간 내 1회만 warning."""
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 없음")

    from app.core.database import is_connection_error
    from app.shared.worker.base_worker import BaseWorker

    worker = FakeWorker()
    orig = psycopg2.OperationalError("connection refused")

    warning_calls = []
    with patch("app.shared.worker.base_worker.logger") as mock_logger:
        mock_logger.warning.side_effect = lambda *a, **kw: warning_calls.append(a)
        for _ in range(100):
            worker._log_worker_error("dispatch", orig)

    # 30초 구간 내 1회
    assert len(warning_calls) == 1


def test_log_worker_error_keeps_full_traceback_for_other_errors_right():
    """비 connection 에러는 exc_info=True ERROR 로깅 유지."""
    worker = FakeWorker()
    exc = ValueError("unexpected value")

    error_calls = []
    with patch("app.shared.worker.base_worker.logger") as mock_logger:
        def capture(*a, **kw):
            error_calls.append(kw)
        mock_logger.error.side_effect = capture
        worker._log_worker_error("some_task", exc)

    assert len(error_calls) == 1
    assert error_calls[0].get("exc_info") is True


def test_worker_heartbeat_published_during_open_state_right():
    """circuit OPEN 상태 루프에서도 _update_heartbeat 호출."""
    from app.core.database import db_circuit, _OPEN
    from app.shared.worker.health_redis import PUBLISH_INTERVAL

    with db_circuit._lock:
        db_circuit._state = _OPEN
        db_circuit._fail_count = 3
        db_circuit._last_fail_time = time.monotonic()

    worker = FakeWorker()
    # heartbeat 시간을 과거로 설정하여 즉시 호출되도록
    worker._last_heartbeat_time = time.monotonic() - PUBLISH_INTERVAL - 1

    heartbeat_called = []
    original_update = worker._update_heartbeat

    def mock_heartbeat():
        heartbeat_called.append(True)
    worker._update_heartbeat = mock_heartbeat

    asyncio.run(worker._main_loop())

    assert len(heartbeat_called) >= 1

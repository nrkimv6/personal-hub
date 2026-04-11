"""tests/test_worker_pg_down_integration.py

PG 다운 시나리오 재현 통합 테스트 (Phase T3 - 항목 11)

실제 DB 연결 없이 잘못된 URL / mock으로 시뮬레이션.
서버 기동 불필요 — 워크트리에서 실행 가능.
"""
import asyncio
import logging
import time
import threading
from unittest.mock import MagicMock, patch

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


# ── 로그 플러드 방지 검증 ──────────────────────────────────────────────────────

def test_worker_does_not_flood_logs_when_pg_down_integration():
    """DB OPEN 상태에서 워커가 WARNING 2건 이하, ERROR traceback 0건 로깅.

    실제 워커 루프를 5 cycle 시뮬레이션하여 검증.
    """
    from app.core.database import db_circuit, _OPEN
    from app.shared.worker.health_redis import PUBLISH_INTERVAL

    # DB OPEN 상태 설정
    with db_circuit._lock:
        db_circuit._state = _OPEN
        db_circuit._fail_count = 3
        db_circuit._last_fail_time = time.monotonic()

    class TestWorker:
        def __init__(self):
            self.name = "flood_test_worker"
            self.shutdown_event = asyncio.Event()
            self._consecutive_errors = 0
            self._max_consecutive_errors = 10
            self._last_heartbeat_time = 0
            self._was_db_unavailable = False
            self._last_db_unavailable_log_time = 0.0
            self._error_log_rate = {}
            self._running_tasks = set()
            self.cycle_count = 0

        def _get_loop_interval(self):
            return 0.01

        def _log_db_unavailable_once(self):
            from app.shared.worker.base_worker import BaseWorker
            BaseWorker._log_db_unavailable_once(self)

        def _cleanup_completed_tasks(self):
            pass

        def _update_heartbeat(self):
            pass

        async def _wait_for_next_cycle(self, interval):
            self.cycle_count += 1
            if self.cycle_count >= 5:
                self.shutdown_event.set()

        async def _main_loop(self):
            from app.shared.worker.base_worker import BaseWorker
            await BaseWorker._main_loop(self)

    worker = TestWorker()

    warning_msgs = []
    error_msgs = []

    with patch("app.shared.worker.base_worker.logger") as mock_logger:
        mock_logger.warning.side_effect = lambda *a, **kw: warning_msgs.append(a)
        mock_logger.error.side_effect = lambda *a, **kw: error_msgs.append(kw)
        asyncio.get_event_loop().run_until_complete(worker._main_loop())

    # PG down 시 WARNING ≤2건 (30초 rate-limit), traceback ERROR 0건
    tb_errors = [e for e in error_msgs if e.get("exc_info")]
    assert len(warning_msgs) <= 2, f"WARNING 초과: {len(warning_msgs)}건 — {warning_msgs}"
    assert len(tb_errors) == 0, f"traceback ERROR 발생: {tb_errors}"


def test_check_db_available_returns_false_on_pg_down_integration():
    """db_circuit OPEN 상태에서 is_available() False 반환."""
    from app.core.database import db_circuit, _OPEN

    with db_circuit._lock:
        db_circuit._state = _OPEN
        db_circuit._fail_count = 3
        db_circuit._last_fail_time = time.monotonic()

    assert db_circuit.is_available() is False
    assert db_circuit.get_status()["state"] == "open"


def test_db_circuit_integrates_with_handle_error_integration():
    """handle_error 훅을 통해 db_circuit.record_failure() 호출 + OPEN 전이 확인."""
    from sqlalchemy import create_engine, text, event
    from sqlalchemy.orm import sessionmaker
    from app.core.database import db_circuit, _CB_THRESHOLD, _CLOSED

    # 접근 불가 URL로 엔진 생성 (포트 1 = closed)
    BAD_URL = "postgresql://nobody:x@localhost:1/nope"

    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 없음")

    # 별도 테스트용 엔진 (기존 엔진 변경 없이)
    test_engine = create_engine(
        BAD_URL,
        pool_pre_ping=True,
        pool_timeout=2,
        connect_args={"connect_timeout": 1},
    )

    # db_circuit에 record_failure를 연결
    @event.listens_for(test_engine, "handle_error")
    def _test_handle_error(ctx):
        from app.core.database import is_connection_error
        if is_connection_error(ctx.original_exception):
            db_circuit.record_failure(ctx.original_exception)

    Session = sessionmaker(bind=test_engine)

    # 임계치(3)번 연결 시도
    for _ in range(_CB_THRESHOLD):
        try:
            db = Session()
            db.execute(text("SELECT 1"))
            db.close()
        except Exception:
            pass

    status = db_circuit.get_status()
    assert status["state"] == "open", f"예상 open, 실제 {status['state']}"
    assert status["fail_count"] >= _CB_THRESHOLD


def test_circuit_does_not_open_on_single_transient_error_right():
    """1회 실패 후 성공 시퀀스에서 circuit OPEN 전이 없음."""
    from app.core.database import db_circuit, _CLOSED

    # 1회 실패 기록
    err = Exception("connection refused")
    db_circuit.record_failure(err)

    # 성공 기록
    db_circuit.record_success()

    assert db_circuit.is_available() is True
    # 1회 실패 후 성공 → fail_count 리셋
    assert db_circuit.get_status()["fail_count"] == 0


def test_stale_connection_via_record_failure_integration():
    """record_failure 반복 호출 시 OPEN 전이 후 record_success로 복구."""
    from app.core.database import db_circuit, _CB_THRESHOLD

    err = Exception("server closed the connection unexpectedly")

    # 임계치 도달
    for _ in range(_CB_THRESHOLD):
        db_circuit.record_failure(err)

    assert db_circuit.get_status()["state"] == "open"

    # 쿨다운 경과 시뮬레이션 → HALF_OPEN
    with db_circuit._lock:
        db_circuit._last_fail_time = time.monotonic() - 11.0

    assert db_circuit.is_available() is True  # HALF_OPEN
    assert db_circuit.get_status()["state"] == "half_open"

    # 성공 → CLOSED
    db_circuit.record_success()
    assert db_circuit.get_status()["state"] == "closed"

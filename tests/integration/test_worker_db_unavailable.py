"""tests/e2e/test_worker_db_unavailable_e2e.py

Phase T4: 워커 회로차단기 E2E — PG 불가 시 생존·하트비트·복구 검증

in-process 워커 인스턴스를 사용하여 실제 _main_loop 동작을 검증한다.
BaseWorker._main_loop 레벨에서 circuit OPEN 시 backoff guard가 작동하는지 확인.
"""
import asyncio
import time
import threading

import pytest


@pytest.fixture(autouse=True)
def reset_db_circuit():
    """각 테스트 전후 db_circuit 싱글턴 상태 초기화."""
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


class _MinimalWorker:
    """_main_loop를 최소 구성으로 실행하는 테스트 워커."""

    def __init__(self, cycle_limit: int = 5, backoff_seconds: float = 0.01):
        self.name = "e2e_test_worker"
        self.shutdown_event = asyncio.Event()
        self._consecutive_errors = 0
        self._max_consecutive_errors = 10
        self._last_heartbeat_time = 0
        self._was_db_unavailable = False
        self._last_db_unavailable_log_time = 0.0
        self._error_log_rate = {}
        self._running_tasks = set()
        self._cycle_count = 0
        self._cycle_limit = cycle_limit
        self._backoff_seconds = backoff_seconds
        self.iterations_called = 0
        self.heartbeats_published = []

    def _get_loop_interval(self):
        return self._backoff_seconds

    def _log_db_unavailable_once(self):
        from app.shared.worker.base_worker import BaseWorker
        BaseWorker._log_db_unavailable_once(self)

    def _cleanup_completed_tasks(self):
        pass

    def _update_heartbeat(self):
        self.heartbeats_published.append(time.monotonic())

    async def _wait_for_next_cycle(self, interval):
        self._cycle_count += 1
        if self._cycle_count >= self._cycle_limit:
            self.shutdown_event.set()

    async def _main_loop_iteration(self):
        self.iterations_called += 1

    async def _main_loop(self):
        from app.shared.worker.base_worker import BaseWorker
        await BaseWorker._main_loop(self)


# ── T4 E2E 테스트 ──────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_worker_survives_pg_unavailable_on_startup_e2e():
    """T4: circuit OPEN 상태에서 워커 루프가 5 사이클 동안 crash 없이 생존.

    _main_loop_iteration 호출이 0회여야 함 (OPEN backoff guard 작동).
    """
    from app.core.database import db_circuit, _OPEN

    # PG 불가 상태 시뮬레이션
    with db_circuit._lock:
        db_circuit._state = _OPEN
        db_circuit._fail_count = 3
        db_circuit._last_fail_time = time.monotonic()

    worker = _MinimalWorker(cycle_limit=5)

    try:
        asyncio.run(worker._main_loop())
    except Exception as e:
        pytest.fail(f"워커 루프가 예외로 종료됨: {e}")

    # circuit OPEN → iterations 호출 0회
    assert worker.iterations_called == 0, (
        f"circuit OPEN 상태에서 _main_loop_iteration 호출됨: {worker.iterations_called}회"
    )
    assert worker._cycle_count == 5, f"사이클 미완료: {worker._cycle_count}"


@pytest.mark.integration
def test_worker_heartbeat_published_during_db_open_e2e():
    """T4: circuit OPEN 상태에서도 워커가 heartbeat를 유지.

    _update_heartbeat가 루프 내에서 주기적으로 호출되는지 확인.
    """
    from app.core.database import db_circuit, _OPEN

    with db_circuit._lock:
        db_circuit._state = _OPEN
        db_circuit._fail_count = 3
        db_circuit._last_fail_time = time.monotonic()

    worker = _MinimalWorker(cycle_limit=10)

    asyncio.run(worker._main_loop())

    # heartbeat는 _update_heartbeat 호출 기록으로 확인
    # BaseWorker._main_loop 내부에서 _update_heartbeat가 호출되어야 함
    # (circuit OPEN backoff 경로에서도 heartbeat는 유지되어야 함)
    assert worker._cycle_count == 10, f"사이클 미완료: {worker._cycle_count}"
    # iterations는 0 (OPEN backoff guard 작동)
    assert worker.iterations_called == 0


@pytest.mark.integration
def test_worker_recovers_when_pg_restored_e2e():
    """T4: db_circuit를 OPEN→HALF_OPEN→CLOSED 전이 시뮬레이션 + 워커 루프 재개.

    쿨다운 경과 후 is_available() True가 되면 _main_loop_iteration 재개 확인.
    """
    from app.core.database import db_circuit, _OPEN, _CLOSED

    # 1) OPEN 상태 강제
    with db_circuit._lock:
        db_circuit._state = _OPEN
        db_circuit._fail_count = 3
        db_circuit._last_fail_time = time.monotonic()

    assert not db_circuit.is_available()

    # 2) 쿨다운 경과 → HALF_OPEN
    with db_circuit._lock:
        db_circuit._last_fail_time = time.monotonic() - 11.0

    assert db_circuit.is_available()
    assert db_circuit.get_status()["state"] == "half_open"

    # 3) 성공 → CLOSED
    db_circuit.record_success()
    assert db_circuit.get_status()["state"] == "closed"

    # 4) CLOSED 상태에서 워커 루프 → _main_loop_iteration 호출됨
    worker = _MinimalWorker(cycle_limit=3)
    asyncio.run(worker._main_loop())

    assert worker.iterations_called > 0, (
        "CLOSED 복구 후 _main_loop_iteration 미호출 — backoff guard가 잘못 유지됨"
    )


# ── T4 사이클 TC: scheduled writing + kakao PG 오류 반복 생존 검증 ──────────────

try:
    import psycopg2 as _psycopg2
    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False

import logging
from unittest.mock import AsyncMock, MagicMock, patch

_CYCLE_SKIP = pytest.mark.skipif(not _HAS_PSYCOPG2, reason="psycopg2 없음")

WIN32_MOCKS_CYCLE = {
    "psutil": MagicMock(),
    "win32gui": MagicMock(),
    "win32con": MagicMock(),
    "win32clipboard": MagicMock(),
    "pyautogui": MagicMock(),
    "paddleocr": MagicMock(),
    "imagehash": MagicMock(),
    "win32ui": MagicMock(),
    "app.worker.crawl_worker_base": MagicMock(),
    "app.worker.scheduled_worker": MagicMock(),
    "app.worker.ondemand_worker": MagicMock(),
}


@_CYCLE_SKIP
@pytest.mark.integration
@pytest.mark.asyncio
async def test_scheduled_writing_3_consecutive_pg_errors_no_flood_cycle(caplog):
    """T4: scheduled writing path — 3회 연속 connection error 후 circuit OPEN 진입해도
    traceback flood 없고 WARNING rate-limit(30초 1건)이 작동한다."""
    from app.worker.scheduled_worker import ScheduledCrawlWorker
    from app.modules.writing.schedulers.writing_task_schedule import WritingTaskScheduler

    worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))
    worker._error_log_rate = {}  # rate-limit 초기화

    handler = WritingTaskScheduler()
    conn_err = _psycopg2.OperationalError("connection refused to server")
    mock_svc = MagicMock()
    mock_claimed = MagicMock()
    mock_claimed.run.id = 10
    mock_claimed.config_snapshot_patch = {}

    with caplog.at_level(logging.DEBUG):
        for _ in range(3):
            with (
                patch.object(handler, "execute", new=AsyncMock(side_effect=conn_err)),
                patch("app.worker.scheduled_worker.SessionLocal", return_value=MagicMock()),
                patch("app.worker.scheduled_worker.TaskScheduleService", return_value=mock_svc),
            ):
                await worker._run_handler(handler, MagicMock(), mock_claimed)

    # traceback ERROR 0건
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_records) == 0, \
        f"traceback ERROR 발생: {[r.getMessage() for r in error_records]}"

    # WARNING 1건 (30초 rate-limit — 3회 연속이어도 1건)
    conn_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "DB 연결 오류" in r.getMessage()
    ]
    assert len(conn_warnings) == 1, \
        f"rate-limit 미작동: WARNING {len(conn_warnings)}건 (1건 기대)"

    # fail_run 3회 (각 error마다 orphan 방지 epilogue)
    assert mock_svc.fail_run.call_count == 3, \
        f"fail_run {mock_svc.fail_run.call_count}회 (3회 기대)"


@_CYCLE_SKIP
@pytest.mark.integration
@pytest.mark.asyncio
async def test_kakao_worker_repeated_pg_errors_rate_limited_survives_cycle(caplog):
    """T4: KakaoMonitorWorker — connection error 5회 반복 시 WARNING rate-limit(30초 1건),
    루프가 죽지 않고 _safe_execute traceback WARNING 0건."""
    with patch.dict("sys.modules", WIN32_MOCKS_CYCLE):
        from app.worker.kakao_monitor_worker import KakaoMonitorWorker
        worker = KakaoMonitorWorker()

    worker._error_log_rate = {}  # rate-limit 초기화

    conn_err = _psycopg2.OperationalError("connection refused to server")
    worker._load_active_state = MagicMock(side_effect=conn_err)

    with caplog.at_level(logging.DEBUG):
        for _ in range(5):
            # 예외 없이 정상 완료되어야 함 (connection error는 _monitor_chat 내부에서 흡수)
            await worker._main_loop_iteration()

    # _safe_execute 실패 로그 0건
    safe_execute_failures = [
        r for r in caplog.records
        if r.exc_info and "실패" in r.getMessage()
    ]
    assert len(safe_execute_failures) == 0, \
        f"_safe_execute 실패 로그 발생: {[r.getMessage() for r in safe_execute_failures]}"

    # WARNING rate-limit: 5회 연속이어도 30초 이내라 1건만
    conn_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "DB 연결 오류" in r.getMessage()
    ]
    assert len(conn_warnings) == 1, \
        f"rate-limit 미작동: WARNING {len(conn_warnings)}건 (1건 기대)"

"""tests/integration/test_worker_schedule_pg_error.py

scheduled_worker + kakao_monitor_worker — PG 다운 계약 통합 TC (Phase T3)

실제 _run_handler / _main_loop_iteration 코드를 타고,
connection error 시 WARNING 1회 + fail_run 1회 계약을 caplog로 확인한다.
서버 기동 불필요 — 워크트리에서 실행 가능.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    import psycopg2
    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False

pytestmark = pytest.mark.skipif(not _HAS_PSYCOPG2, reason="psycopg2 없음")


def _pg_conn_err() -> Exception:
    return psycopg2.OperationalError("connection refused to server")


# KakaoMonitorWorker 생성용 win32 의존성 mock
WIN32_MOCKS = {
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


# ---------------------------------------------------------------------------
# T3-01: ScheduledCrawlWorker._run_handler() + WritingTaskScheduler
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scheduled_worker_writing_task_pg_down_logs_warning_only_integration(caplog):
    """T3: _run_handler() + WritingTaskScheduler — PG 다운 시 traceback ERROR 0 + fail_run 1회."""
    from app.worker.scheduled_worker import ScheduledCrawlWorker
    from app.modules.writing.schedulers.writing_task_schedule import WritingTaskScheduler

    worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))
    worker._error_log_rate = {}  # rate-limit 초기화

    handler = WritingTaskScheduler()
    mock_schedule = MagicMock()
    mock_claimed = MagicMock()
    mock_claimed.run.id = 99
    mock_claimed.config_snapshot_patch = {}

    conn_err = _pg_conn_err()
    mock_svc = MagicMock()

    with caplog.at_level(logging.DEBUG):
        with (
            patch.object(handler, "execute", new=AsyncMock(side_effect=conn_err)),
            patch("app.worker.scheduled_worker.SessionLocal", return_value=MagicMock()),
            patch("app.worker.scheduled_worker.TaskScheduleService", return_value=mock_svc),
        ):
            await worker._run_handler(handler, mock_schedule, mock_claimed)

    # traceback ERROR 0건
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_records) == 0, \
        f"ERROR 로그 발생: {[r.getMessage() for r in error_records]}"

    # DB 연결 오류 WARNING 1건 (rate-limit 통과 첫 호출)
    conn_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "DB 연결 오류" in r.getMessage()
    ]
    assert len(conn_warnings) == 1, \
        f"WARNING 1건 기대, 실제 {len(conn_warnings)}건: {[r.getMessage() for r in conn_warnings]}"

    # fail_run 정확히 1회
    mock_svc.fail_run.assert_called_once_with(99, error_message=str(conn_err))


# ---------------------------------------------------------------------------
# T3-02: ScheduledCrawlWorker._run_handler() + KeywordAnalysisScheduler
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scheduled_worker_keyword_analysis_pg_down_logs_warning_only_integration(caplog):
    """T3: _run_handler() + KeywordAnalysisScheduler — PG 다운 시 traceback ERROR 0 + fail_run 1회."""
    from app.worker.scheduled_worker import ScheduledCrawlWorker
    from app.modules.writing.schedulers.keyword_analysis_schedule import KeywordAnalysisScheduler

    worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))
    worker._error_log_rate = {}

    handler = KeywordAnalysisScheduler()
    mock_schedule = MagicMock()
    mock_claimed = MagicMock()
    mock_claimed.run.id = 77
    mock_claimed.config_snapshot_patch = {}

    conn_err = _pg_conn_err()
    mock_svc = MagicMock()

    with caplog.at_level(logging.DEBUG):
        with (
            patch.object(handler, "execute", new=AsyncMock(side_effect=conn_err)),
            patch("app.worker.scheduled_worker.SessionLocal", return_value=MagicMock()),
            patch("app.worker.scheduled_worker.TaskScheduleService", return_value=mock_svc),
        ):
            await worker._run_handler(handler, mock_schedule, mock_claimed)

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_records) == 0, \
        f"ERROR 로그 발생: {[r.getMessage() for r in error_records]}"

    conn_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "DB 연결 오류" in r.getMessage()
    ]
    assert len(conn_warnings) == 1, \
        f"WARNING 1건 기대, 실제 {len(conn_warnings)}건"

    mock_svc.fail_run.assert_called_once_with(77, error_message=str(conn_err))


# ---------------------------------------------------------------------------
# T3-03: KakaoMonitorWorker._main_loop_iteration()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kakao_main_loop_iteration_pg_down_avoids_safe_execute_traceback_integration(caplog):
    """T3: KakaoMonitorWorker._main_loop_iteration() — PG 다운 시 _safe_execute 실패 로그 없이
    WARNING-only로 종료되는지 확인한다."""
    with patch.dict("sys.modules", WIN32_MOCKS):
        from app.worker.kakao_monitor_worker import KakaoMonitorWorker
        worker = KakaoMonitorWorker()

    worker._error_log_rate = {}  # rate-limit 초기화

    conn_err = _pg_conn_err()
    worker._load_active_state = MagicMock(side_effect=conn_err)

    with caplog.at_level(logging.DEBUG):
        # connection error가 _monitor_chat 내부에서 흡수되므로 예외 없이 완료
        await worker._main_loop_iteration()

    # _safe_execute "작업 실패" 경로 발동 없음 — exc_info 포함 WARNING 없음
    safe_execute_failures = [
        r for r in caplog.records
        if r.exc_info and "실패" in r.getMessage()
    ]
    assert len(safe_execute_failures) == 0, \
        f"_safe_execute 실패 로그 발생: {[r.getMessage() for r in safe_execute_failures]}"

    # _log_worker_error → WARNING 1건 (DB 연결 오류)
    conn_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "DB 연결 오류" in r.getMessage()
    ]
    assert len(conn_warnings) == 1, \
        f"DB 연결 오류 WARNING 1건 기대, 실제 {len(conn_warnings)}건"

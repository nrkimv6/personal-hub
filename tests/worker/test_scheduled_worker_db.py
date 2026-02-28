"""
TC: scheduled_worker._dispatch_scheduled_runs() DB 세션 누수 방지
- RIGHT: 정상 실행 후 db.close() 호출 검증
- ERROR: 내부 예외 발생 시에도 db.close() 호출 검증
- PERFORMANCE: 루프 반복 후 pool 연결 수 증가 없음 검증
"""
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ScheduledWorker 임포트 시 DB/Redis 연결이 필요하므로 최소한의 의존성만 patch
@pytest.fixture
def worker():
    with (
        patch("app.worker.scheduled_worker.SessionLocal"),
        patch("app.worker.scheduled_worker.redis"),
        patch("app.worker.base_worker.redis"),
    ):
        from app.worker.scheduled_worker import ScheduledWorker
        w = ScheduledWorker.__new__(ScheduledWorker)
        w.name = "test-scheduled-worker"
        w._last_stale_cleanup = None
        return w


def test_dispatch_scheduled_runs_right_db_closed_after_success(worker):
    """R: 정상 실행 후 db.close() 반드시 호출됨"""
    mock_db = MagicMock()
    mock_service = MagicMock()
    mock_service.get_schedules_by_type.return_value = []

    with (
        patch("app.worker.scheduled_worker.SessionLocal", return_value=mock_db),
        patch("app.worker.scheduled_worker.TaskScheduleService", return_value=mock_service),
    ):
        asyncio.get_event_loop().run_until_complete(worker._dispatch_scheduled_runs())

    mock_db.close.assert_called_once()


def test_dispatch_scheduled_runs_error_db_closed_after_exception(worker):
    """E: get_schedules_by_type에서 예외 발생해도 db.close() 반드시 호출됨"""
    mock_db = MagicMock()
    mock_service = MagicMock()
    mock_service.get_schedules_by_type.side_effect = RuntimeError("DB 연결 오류")

    with (
        patch("app.worker.scheduled_worker.SessionLocal", return_value=mock_db),
        patch("app.worker.scheduled_worker.TaskScheduleService", return_value=mock_service),
    ):
        asyncio.get_event_loop().run_until_complete(worker._dispatch_scheduled_runs())

    mock_db.close.assert_called_once()


def test_dispatch_no_pool_exhaustion_after_repeated_calls(worker):
    """P: 10회 반복 호출 후 db.close() 호출 횟수 = 10 (누수 없음)"""
    mock_db = MagicMock()
    mock_service = MagicMock()
    mock_service.get_schedules_by_type.return_value = []

    with (
        patch("app.worker.scheduled_worker.SessionLocal", return_value=mock_db),
        patch("app.worker.scheduled_worker.TaskScheduleService", return_value=mock_service),
    ):
        loop = asyncio.get_event_loop()
        for _ in range(10):
            loop.run_until_complete(worker._dispatch_scheduled_runs())

    assert mock_db.close.call_count == 10

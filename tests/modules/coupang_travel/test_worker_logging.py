"""
워커 로그 출력 경계 검증 (T1 — BICEP Boundary)

스케줄 없을 때 DEBUG "스킵" 로그 출력 여부를 caplog으로 검증.
"""
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def worker_with_service():
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker

    mock_browser = MagicMock()
    worker = CoupangMonitorWorker(browser_manager=mock_browser)
    worker._monitor_service = AsyncMock()
    return worker


@pytest.mark.asyncio
async def test_no_active_schedules_logs_debug(worker_with_service, caplog):
    """B(Boundary): 스케줄 0건 반환 시 DEBUG 로그에 '스킵' 포함."""
    worker = worker_with_service
    mock_db = MagicMock()
    mock_db.close = MagicMock()
    mock_schedule_service = MagicMock()
    mock_schedule_service.get_all_with_context.return_value = []

    with caplog.at_level(logging.DEBUG, logger="app.worker.coupang_monitor_worker"):
        with (
            patch("app.worker.coupang_monitor_worker.schedule_service", mock_schedule_service),
            patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=mock_db),
        ):
            await worker._main_loop_iteration()

    skip_logs = [r for r in caplog.records if "스킵" in r.message]
    assert len(skip_logs) >= 1, f"'스킵' DEBUG 로그가 없음. 실제 로그: {[r.message for r in caplog.records]}"


@pytest.mark.asyncio
async def test_active_schedules_no_debug_skip_log(worker_with_service, caplog):
    """B(Boundary): 스케줄 1건+ 존재 시 '스킵' DEBUG 로그 미출력."""
    worker = worker_with_service
    worker._safe_execute = AsyncMock()  # 실제 check_schedule 실행 방지

    mock_db = MagicMock()
    mock_db.close = MagicMock()
    mock_schedule_service = MagicMock()
    mock_schedule_service.get_all_with_context.return_value = [
        {"id": 1, "item_biz_item_id": "99999", "date": "2026-05-01", "service_account_id": 1}
    ]

    with caplog.at_level(logging.DEBUG, logger="app.worker.coupang_monitor_worker"):
        with (
            patch("app.worker.coupang_monitor_worker.schedule_service", mock_schedule_service),
            patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=mock_db),
        ):
            await worker._main_loop_iteration()

    skip_logs = [r for r in caplog.records if "스킵" in r.message]
    assert len(skip_logs) == 0, f"스케줄 존재 시 '스킵' 로그가 출력됨: {[r.message for r in skip_logs]}"

"""
워커 null account 처리 검증 (T1 — RIGHT-BICEP)

service_account_id=None 전달 시 tab_pool_manager.get_tab(schedule_id, None) 호출 확인.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_worker():
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker

    mock_browser = MagicMock()
    mock_page = MagicMock()
    mock_page.url = "https://trip.coupang.com/tp/products/99999"
    mock_page.context = MagicMock()
    mock_browser.tab_pool_manager = MagicMock()
    mock_browser.tab_pool_manager.get_tab = AsyncMock(return_value=mock_page)
    mock_browser.tab_pool_manager.release_tab = AsyncMock()

    worker = CoupangMonitorWorker(browser_manager=mock_browser)
    worker._monitor_service = AsyncMock()
    worker._monitor_service.check_and_notify = AsyncMock(return_value=[])
    return worker, mock_browser, mock_page


@pytest.mark.asyncio
async def test_check_schedule_null_service_account_uses_default_context(mock_worker):
    """R(Right): service_account_id=None 전달 시 tab_pool_manager.get_tab(101, None) 호출됨."""
    worker, mock_browser, _ = mock_worker

    ctx = {
        "id": 101,
        "item_biz_item_id": "99999",
        "date": "2026-05-01",
        "service_account_id": None,  # null account
        "biz_item_pk": 1,
    }

    mock_db = MagicMock()
    mock_db.close = MagicMock()
    mock_schedule_service = MagicMock()

    with (
        patch.object(worker, "_extract_vendor_item_package_id", return_value="pkg_test"),
        patch("app.worker.coupang_monitor_worker.schedule_service", mock_schedule_service),
        patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=mock_db),
    ):
        await worker._check_schedule(ctx)

    mock_browser.tab_pool_manager.get_tab.assert_called_once_with(101, None)


@pytest.mark.asyncio
async def test_check_schedule_with_service_account_uses_account_context(mock_worker):
    """R(Right): service_account_id=42 전달 시 tab_pool_manager.get_tab(102, 42) 호출됨."""
    worker, mock_browser, _ = mock_worker

    ctx = {
        "id": 102,
        "item_biz_item_id": "99999",
        "date": "2026-05-01",
        "service_account_id": 42,
        "biz_item_pk": 1,
    }

    mock_db = MagicMock()
    mock_db.close = MagicMock()
    mock_schedule_service = MagicMock()

    with (
        patch.object(worker, "_extract_vendor_item_package_id", return_value="pkg_test"),
        patch("app.worker.coupang_monitor_worker.schedule_service", mock_schedule_service),
        patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=mock_db),
    ):
        await worker._check_schedule(ctx)

    mock_browser.tab_pool_manager.get_tab.assert_called_once_with(102, 42)

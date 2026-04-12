"""
워커 null account 처리 검증 (T1 — RIGHT-BICEP)

service_account_id=None 전달 시 browser.get_context(None) 호출 확인.
기존 test_coupang_e2e.py L318-335 패턴 참조.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_worker():
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker

    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()
    mock_page.url = "https://trip.coupang.com/tp/products/99999"
    mock_context.pages = [mock_page]
    mock_browser.get_context = AsyncMock(return_value=mock_context)

    worker = CoupangMonitorWorker(browser_manager=mock_browser)
    worker._monitor_service = AsyncMock()
    worker._monitor_service.check_and_notify = AsyncMock(return_value=[])
    return worker, mock_browser, mock_context, mock_page


@pytest.mark.asyncio
async def test_check_schedule_null_service_account_uses_default_context(mock_worker):
    """R(Right): service_account_id=None 전달 시 browser.get_context(None) 호출됨."""
    worker, mock_browser, _, _ = mock_worker

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

    # get_context가 None으로 호출되었는지 확인
    mock_browser.get_context.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_check_schedule_with_service_account_uses_account_context(mock_worker):
    """R(Right): service_account_id=42 전달 시 browser.get_context(42) 호출됨."""
    worker, mock_browser, _, _ = mock_worker

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

    # get_context가 42로 호출되었는지 확인
    mock_browser.get_context.assert_called_once_with(42)

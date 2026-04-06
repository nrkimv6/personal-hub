"""
워커 테스트 (RIGHT-BICEP: R, E)
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.coupang_travel.services.api_client import VendorItem


@pytest.fixture
def mock_schedule_context():
    return [
        {
            "id": 1,
            "item_biz_item_id": "123",
            "date": "2026-04-10",
            "service_account_id": 10,
            "biz_item_pk": 5,
        },
        {
            "id": 2,
            "item_biz_item_id": "456",
            "date": "2026-04-11",
            "service_account_id": 10,
            "biz_item_pk": 6,
        },
    ]


@pytest.mark.asyncio
async def test_worker_schedule_filter_service_type(mock_schedule_context):
    """R: schedule_service 호출 시 service_type='coupang' 인자 확인"""
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker

    worker = CoupangMonitorWorker(browser_manager=None)
    worker._monitor_service = AsyncMock()
    worker._api_client = AsyncMock()

    mock_schedule_service = MagicMock()
    mock_schedule_service.get_all_with_context = MagicMock(return_value=[])

    mock_db = MagicMock()

    with (
        patch("app.worker.coupang_monitor_worker.schedule_service", mock_schedule_service),
        patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=mock_db),
    ):
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.close = MagicMock()

        await worker._main_loop_iteration()

    mock_schedule_service.get_all_with_context.assert_called_once()
    call_kwargs = mock_schedule_service.get_all_with_context.call_args
    assert call_kwargs.kwargs.get("service_type") == "coupang"


@pytest.mark.asyncio
async def test_worker_main_loop_iteration(mock_schedule_context):
    """R: 스케줄 2건 반환 시 _check_schedule 2회 호출 확인"""
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker

    worker = CoupangMonitorWorker(browser_manager=None)
    worker._monitor_service = AsyncMock()
    worker._api_client = AsyncMock()
    worker._check_schedule = AsyncMock()

    mock_schedule_service = MagicMock()
    mock_schedule_service.get_all_with_context = MagicMock(return_value=mock_schedule_context)

    mock_db = MagicMock()
    mock_db.close = MagicMock()

    with (
        patch("app.worker.coupang_monitor_worker.schedule_service", mock_schedule_service),
        patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=mock_db),
    ):
        await worker._main_loop_iteration()

    assert worker._check_schedule.call_count == 2


@pytest.mark.asyncio
async def test_monitor_service_uses_stable_vendor_key():
    """R: vendorItemName이 있으면 이름 기반 키로 상태 추적 (이름 변경시 키 충돌 없음)"""
    from app.modules.coupang_travel.services.monitor_service import CoupangMonitorService, _make_vendor_key

    vi1 = VendorItem(vendor_item_name="옵션A", sale_status="ON_SALE", stock_count=1)
    vi2 = VendorItem(vendor_item_name="옵션A", sale_status="ON_SALE", stock_count=1)

    key1 = _make_vendor_key(vi1, 0)
    key2 = _make_vendor_key(vi2, 0)
    assert key1 == key2  # 동일 이름 → 동일 키


@pytest.mark.asyncio
async def test_worker_uses_service_account_context():
    """R: 스케줄의 service_account_id로 browser.get_context 호출 확인"""
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker
    from app.modules.coupang_travel.services.api_client import VendorItem

    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()
    mock_page.url = "https://trip.coupang.com/tp/products/123"
    mock_context.pages = [mock_page]
    mock_browser.get_context = AsyncMock(return_value=mock_context)

    worker = CoupangMonitorWorker(browser_manager=mock_browser)
    worker._monitor_service = AsyncMock()
    worker._monitor_service.check_and_notify = AsyncMock(return_value=[])

    ctx = {
        "id": 1,
        "item_biz_item_id": "123",
        "date": "2026-04-10",
        "service_account_id": 99,
        "biz_item_pk": 5,
    }

    mock_db = MagicMock()
    mock_db.close = MagicMock()
    mock_schedule_service = MagicMock()

    with (
        patch.object(worker, "_extract_vendor_item_package_id", return_value="pkg456"),
        patch("app.worker.coupang_monitor_worker.schedule_service", mock_schedule_service),
        patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=mock_db),
    ):
        await worker._check_schedule(ctx)

    mock_browser.get_context.assert_called_once_with(99)


@pytest.mark.asyncio
async def test_worker_passes_schedule_id_to_check_and_notify():
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker

    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()
    mock_page.url = "https://trip.coupang.com/tp/products/123"
    mock_context.pages = [mock_page]
    mock_browser.get_context = AsyncMock(return_value=mock_context)

    worker = CoupangMonitorWorker(browser_manager=mock_browser)
    worker._monitor_service = AsyncMock()
    worker._monitor_service.check_and_notify = AsyncMock(return_value=[])

    ctx = {
        "id": 7,
        "item_biz_item_id": "123",
        "date": "2026-04-10",
        "service_account_id": 77,
        "biz_item_pk": 5,
    }

    mock_db = MagicMock()
    mock_db.close = MagicMock()
    mock_schedule_service = MagicMock()

    with (
        patch.object(worker, "_extract_vendor_item_package_id", return_value="pkg456"),
        patch("app.worker.coupang_monitor_worker.schedule_service", mock_schedule_service),
        patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=mock_db),
    ):
        await worker._check_schedule(ctx)

    kwargs = worker._monitor_service.check_and_notify.call_args.kwargs
    assert kwargs["schedule_id"] == 7


@pytest.mark.asyncio
async def test_worker_sets_active_true_false_around_check():
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker

    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()
    mock_page.url = "https://trip.coupang.com/tp/products/123"
    mock_context.pages = [mock_page]
    mock_browser.get_context = AsyncMock(return_value=mock_context)

    worker = CoupangMonitorWorker(browser_manager=mock_browser)
    worker._monitor_service = AsyncMock()
    worker._monitor_service.check_and_notify = AsyncMock(return_value=[])

    ctx = {
        "id": 8,
        "item_biz_item_id": "123",
        "date": "2026-04-10",
        "service_account_id": 77,
        "biz_item_pk": 5,
    }

    mock_db = MagicMock()
    mock_db.close = MagicMock()
    mock_schedule_service = MagicMock()

    with (
        patch.object(worker, "_extract_vendor_item_package_id", return_value="pkg456"),
        patch("app.worker.coupang_monitor_worker.schedule_service", mock_schedule_service),
        patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=mock_db),
    ):
        await worker._check_schedule(ctx)

    assert mock_schedule_service.set_active.call_count == 2
    first_call = mock_schedule_service.set_active.call_args_list[0]
    second_call = mock_schedule_service.set_active.call_args_list[1]
    assert first_call.args[1] == 8 and first_call.args[2] is True
    assert second_call.args[1] == 8 and second_call.args[2] is False

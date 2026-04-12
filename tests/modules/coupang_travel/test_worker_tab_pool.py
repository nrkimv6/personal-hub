"""
쿠팡 워커 탭 풀 전환 검증 (Phase T1 — RIGHT-BICEP)

_check_via_playwright()가 tab_pool_manager를 통해 탭을 획득/반환하는지,
팝업 차단 핸들러가 동작하는지 검증.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


def _make_worker_with_tab_pool(url="https://trip.coupang.com/tp/products/123"):
    """tab_pool_manager mock이 설정된 워커 생성 헬퍼."""
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker

    mock_browser = MagicMock()
    mock_page = AsyncMock()
    mock_page.url = url
    mock_page.context = MagicMock()
    mock_browser.tab_pool_manager = MagicMock()
    mock_browser.tab_pool_manager.get_tab = AsyncMock(return_value=mock_page)
    mock_browser.tab_pool_manager.release_tab = AsyncMock()

    worker = CoupangMonitorWorker(browser_manager=mock_browser)
    worker._monitor_service = AsyncMock()
    worker._monitor_service.check_and_notify = AsyncMock(return_value=[])
    return worker, mock_browser, mock_page


@pytest.mark.asyncio
async def test_coupang_worker_uses_tab_pool_R():
    """R(Right): _check_schedule 정상 실행 시 get_tab(schedule_id, service_account_id) 호출,
    완료 후 release_tab(page) 호출 검증."""
    worker, mock_browser, mock_page = _make_worker_with_tab_pool()

    ctx = {
        "id": 10,
        "item_biz_item_id": "123",
        "date": "2026-04-10",
        "service_account_id": 55,
        "biz_item_pk": 5,
    }
    mock_db = MagicMock()
    mock_db.close = MagicMock()
    mock_schedule_service = MagicMock()

    with (
        patch.object(worker, "_extract_vendor_item_package_id", return_value="pkg_abc"),
        patch("app.worker.coupang_monitor_worker.schedule_service", mock_schedule_service),
        patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=mock_db),
    ):
        await worker._check_schedule(ctx)

    mock_browser.tab_pool_manager.get_tab.assert_called_once_with(10, 55)
    mock_browser.tab_pool_manager.release_tab.assert_called_once_with(mock_page)


@pytest.mark.asyncio
async def test_coupang_worker_releases_tab_on_error_E():
    """E(Error): check_and_notify가 예외를 raise할 때 finally에서 release_tab(page) 반드시 호출."""
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker

    mock_browser = MagicMock()
    mock_page = AsyncMock()
    mock_page.url = "https://trip.coupang.com/tp/products/123"
    mock_page.context = MagicMock()
    mock_browser.tab_pool_manager = MagicMock()
    mock_browser.tab_pool_manager.get_tab = AsyncMock(return_value=mock_page)
    mock_browser.tab_pool_manager.release_tab = AsyncMock()

    worker = CoupangMonitorWorker(browser_manager=mock_browser)
    worker._monitor_service = AsyncMock()
    worker._monitor_service.check_and_notify = AsyncMock(side_effect=RuntimeError("API 오류"))

    ctx = {
        "id": 20,
        "item_biz_item_id": "123",
        "date": "2026-04-10",
        "service_account_id": 5,
        "biz_item_pk": 5,
    }
    mock_db = MagicMock()
    mock_db.close = MagicMock()
    mock_schedule_service = MagicMock()

    with (
        patch.object(worker, "_extract_vendor_item_package_id", return_value="pkg_abc"),
        patch("app.worker.coupang_monitor_worker.schedule_service", mock_schedule_service),
        patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=mock_db),
    ):
        with pytest.raises(RuntimeError, match="API 오류"):
            await worker._check_schedule(ctx)

    # 예외가 발생해도 release_tab 반드시 호출
    mock_browser.tab_pool_manager.release_tab.assert_called_once_with(mock_page)


@pytest.mark.asyncio
async def test_coupang_worker_no_tab_pool_skip_B():
    """B(Boundary): tab_pool_manager가 None일 때 경고 로그 출력 후 조기 return,
    get_tab/release_tab 호출 없음 검증."""
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker

    mock_browser = MagicMock()
    mock_browser.tab_pool_manager = None  # None으로 설정

    worker = CoupangMonitorWorker(browser_manager=mock_browser)
    worker._monitor_service = AsyncMock()
    worker._monitor_service.check_and_notify = AsyncMock(return_value=[])

    ctx = {
        "id": 30,
        "item_biz_item_id": "123",
        "date": "2026-04-10",
        "service_account_id": 5,
        "biz_item_pk": 5,
    }
    mock_db = MagicMock()
    mock_db.close = MagicMock()
    mock_schedule_service = MagicMock()

    with (
        patch.object(worker, "_extract_vendor_item_package_id", return_value="pkg_abc"),
        patch("app.worker.coupang_monitor_worker.schedule_service", mock_schedule_service),
        patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=mock_db),
        patch("app.worker.coupang_monitor_worker.logger") as mock_logger,
    ):
        await worker._check_schedule(ctx)

    # TabPoolManager 없음 경고가 발생해야 함
    warning_messages = [str(c) for c in mock_logger.warning.call_args_list]
    assert any("TabPoolManager 없음" in msg for msg in warning_messages)
    # check_and_notify는 호출되지 않아야 함
    worker._monitor_service.check_and_notify.assert_not_called()


@pytest.mark.asyncio
async def test_coupang_worker_popup_blocked_R():
    """R(Right): 팝업 핸들러 등록 후 context에서 새 페이지 이벤트 발생 시 popup.close() 호출."""
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker

    mock_browser = MagicMock()
    mock_page = AsyncMock()
    mock_page.url = "https://trip.coupang.com/tp/products/123"

    # context mock — on() 호출을 캡처하여 핸들러 수동 호출
    popup_handler = None
    mock_context = MagicMock()

    def capture_on(event, handler):
        nonlocal popup_handler
        if event == "page":
            popup_handler = handler

    mock_context.on.side_effect = capture_on
    mock_page.context = mock_context

    mock_browser.tab_pool_manager = MagicMock()
    mock_browser.tab_pool_manager.get_tab = AsyncMock(return_value=mock_page)
    mock_browser.tab_pool_manager.release_tab = AsyncMock()

    worker = CoupangMonitorWorker(browser_manager=mock_browser)
    worker._monitor_service = AsyncMock()
    worker._monitor_service.check_and_notify = AsyncMock(return_value=[])

    ctx = {
        "id": 40,
        "item_biz_item_id": "123",
        "date": "2026-04-10",
        "service_account_id": 5,
        "biz_item_pk": 5,
    }
    mock_db = MagicMock()
    mock_db.close = MagicMock()
    mock_schedule_service = MagicMock()

    with (
        patch.object(worker, "_extract_vendor_item_package_id", return_value="pkg_abc"),
        patch("app.worker.coupang_monitor_worker.schedule_service", mock_schedule_service),
        patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=mock_db),
    ):
        await worker._check_schedule(ctx)

    # context.on("page", handler)가 등록되어 있어야 함
    mock_context.on.assert_called_once_with("page", popup_handler)

    # 팝업 핸들러 호출 시 popup.close() 가 호출되어야 함
    assert popup_handler is not None
    mock_popup = AsyncMock()
    await popup_handler(mock_popup)
    mock_popup.close.assert_called_once()

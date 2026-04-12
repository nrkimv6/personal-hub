"""
탭 누수 없음 통합 검증 (Phase T3 — 재현/통합 TC)

_main_loop_iteration 반복 실행 시 get_tab 호출 횟수 == release_tab 호출 횟수
임을 검증하여 탭 누수가 발생하지 않음을 확인.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_coupang_worker_repeated_iteration_no_tab_leak_C():
    """C(Cross-check): 3회 반복 실행 시 get_tab 호출 수 == release_tab 호출 수
    (탭 누수 없음 확인)."""
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker

    # tab_pool_manager mock
    mock_page = AsyncMock()
    mock_page.url = "https://trip.coupang.com/tp/products/99999"
    mock_page.context = MagicMock()

    mock_tab_pool = MagicMock()
    mock_tab_pool.get_tab = AsyncMock(return_value=mock_page)
    mock_tab_pool.release_tab = AsyncMock()

    mock_browser = MagicMock()
    mock_browser.tab_pool_manager = mock_tab_pool

    worker = CoupangMonitorWorker(browser_manager=mock_browser)
    worker._monitor_service = AsyncMock()
    worker._monitor_service.check_and_notify = AsyncMock(return_value=[])

    # 스케줄 1건 (반복마다 동일 스케줄)
    schedules = [
        {
            "id": 1,
            "item_biz_item_id": "99999",
            "date": "2026-04-15",
            "service_account_id": 5,
            "biz_item_pk": 1,
        }
    ]

    mock_db = MagicMock()
    mock_db.close = MagicMock()
    mock_schedule_service = MagicMock()
    mock_schedule_service.get_all_with_context = MagicMock(return_value=schedules)

    # HTTP 클라이언트가 None이면 _check_via_http가 None 반환 → Playwright fallback
    # → get_tab/release_tab 사용

    with (
        patch.object(worker, "_extract_vendor_item_package_id", return_value="pkg_test"),
        patch("app.worker.coupang_monitor_worker.schedule_service", mock_schedule_service),
        patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=mock_db),
        patch.object(worker, "_set_schedule_active"),
    ):
        # 3회 반복
        for _ in range(3):
            await worker._main_loop_iteration()

    get_tab_count = mock_tab_pool.get_tab.call_count
    release_tab_count = mock_tab_pool.release_tab.call_count

    assert get_tab_count == 3, f"get_tab 3회 호출 기대, 실제: {get_tab_count}"
    assert release_tab_count == 3, f"release_tab 3회 호출 기대, 실제: {release_tab_count}"
    assert get_tab_count == release_tab_count, (
        f"탭 누수 감지: get_tab={get_tab_count} != release_tab={release_tab_count}"
    )

"""
Phase T3: ActivityWorker 탭 release_tab round-trip 통합 TC

실제 TabPoolManager 인스턴스 + mock Playwright context 사용.
_crawl_center() 완료/실패 후 tab_in_use[tab_id] == False 검증.
"""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_pool_with_one_tab(account_id=1):
    """실제 TabPoolManager + mock 탭 1개 픽스처."""
    with patch('app.shared.browser.tab_pool_manager.settings') as ms:
        ms.TAB_ROTATION_THRESHOLD = 600
        ms.CACHE_CLEANUP_INTERVAL = 300
        ms.TAB_REQUEST_TIMEOUT = 60
        ms.TAB_WAIT_RETRY_INTERVAL = 0.05
        ms.TOTAL_MAX_TABS = 5
        ms.MAX_USES_PER_TAB = 50
        from app.shared.browser.tab_pool_manager import TabPoolManager
        pool = TabPoolManager(MagicMock())

    tab_id = f"{account_id}_9001"
    mock_tab = MagicMock()
    mock_tab._tab_id = tab_id
    mock_tab._account_id = account_id
    mock_tab._target_id = None
    mock_tab.close = AsyncMock()
    mock_tab.is_closed = MagicMock(return_value=False)
    mock_tab.evaluate = AsyncMock(return_value=True)  # _is_tab_closed await 통과

    pool.tab_pools[account_id] = {tab_id: mock_tab}
    pool.tab_pool[tab_id] = mock_tab
    pool.tab_last_used[tab_id] = time.time() - 1
    pool.tab_in_use[tab_id] = False
    pool.tab_use_count[tab_id] = 0
    pool.tab_account[tab_id] = account_id
    pool.total_active_tabs = 1

    pool.context_manager.get_or_create_context = AsyncMock(
        return_value=MagicMock(pages=[mock_tab])
    )
    pool.cleanup_old_tabs = AsyncMock(return_value=0)
    return pool, tab_id, mock_tab


def _make_activity_worker_with_pool(pool):
    """실제 pool을 주입받은 ActivityWorker + mock BrowserManager."""
    from app.worker.activity_worker import ActivityWorker

    mock_browser = MagicMock()
    mock_browser.tab_pool_manager = pool
    worker = ActivityWorker(browser_manager=mock_browser)
    return worker


@pytest.mark.asyncio
async def test_activity_worker_tab_roundtrip_with_real_pool():
    """T3-R: _crawl_center 정상 완료 후 tab_in_use[tab_id] == False 검증.

    실제 TabPoolManager → get_tab 획득 → crawl(mock) → release_tab round-trip.
    """
    pool, tab_id, mock_tab = _make_pool_with_one_tab()
    worker = _make_activity_worker_with_pool(pool)

    center = MagicMock()
    center.id = 42
    center.name = "테스트센터"
    center.crawl_method = "dynamic"

    mock_result = MagicMock()
    mock_result.status = "success"
    mock_result.error_message = None
    mock_crawler = AsyncMock()
    mock_crawler.crawl = AsyncMock(return_value=mock_result)

    assert pool.tab_in_use[tab_id] is False, "초기 상태: in_use=False"

    with (
        patch("app.worker.activity_worker.ActivityWorker._ensure_browser_initialized", new_callable=AsyncMock),
        patch("app.modules.activity.crawlers.get_crawler", return_value=mock_crawler),
        patch("app.modules.activity.services.import_service.ImportService"),
        patch("app.worker.activity_worker.SessionLocal"),
    ):
        await worker._crawl_center(center, crawl_run_id=1)

    assert pool.tab_in_use.get(tab_id, False) is False, \
        f"crawl 완료 후 tab_in_use[{tab_id}] 반드시 False여야 함 — 누락 시 starvation 재발"


@pytest.mark.asyncio
async def test_activity_worker_tab_not_leaked_on_crawler_failure():
    """T3-E: crawler.crawl() 예외 시에도 tab_in_use[tab_id] == False 검증.

    예외 발생 경로에서도 release_tab이 호출되어 풀 상태가 복원되는지 확인.
    """
    pool, tab_id, mock_tab = _make_pool_with_one_tab()
    worker = _make_activity_worker_with_pool(pool)

    center = MagicMock()
    center.id = 42
    center.name = "테스트센터"
    center.crawl_method = "dynamic"

    mock_crawler = AsyncMock()
    mock_crawler.crawl = AsyncMock(side_effect=RuntimeError("크롤링 실패"))

    assert pool.tab_in_use[tab_id] is False, "초기 상태: in_use=False"

    with (
        patch("app.worker.activity_worker.ActivityWorker._ensure_browser_initialized", new_callable=AsyncMock),
        patch("app.modules.activity.crawlers.get_crawler", return_value=mock_crawler),
        patch("app.modules.activity.services.import_service.ImportService"),
        patch("app.worker.activity_worker.SessionLocal"),
    ):
        with pytest.raises(RuntimeError):
            await worker._crawl_center(center, crawl_run_id=1)

    assert pool.tab_in_use.get(tab_id, False) is False, \
        f"예외 후 tab_in_use[{tab_id}] 반드시 False여야 함 — 누락 시 starvation 재발"

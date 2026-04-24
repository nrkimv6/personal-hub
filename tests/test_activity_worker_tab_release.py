"""
ActivityWorker 동적 크롤링 탭 release_tab 계약 검증 (Phase T1 — RIGHT-BICEP)

_crawl_center()가 dynamic 크롤링 시 get_tab 획득 후 finally에서
반드시 asyncio.shield(release_tab())를 호출하는지 검증.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_worker(browser=True):
    """test용 ActivityWorker 헬퍼."""
    from app.worker.activity_worker import ActivityWorker

    if browser:
        mock_browser = MagicMock()
        mock_page = AsyncMock()
        mock_browser.tab_pool_manager = MagicMock()
        mock_browser.tab_pool_manager.get_tab = AsyncMock(return_value=mock_page)
        mock_browser.tab_pool_manager.release_tab = AsyncMock()
        mock_browser.is_initialized = True
    else:
        mock_browser = None
        mock_page = None

    worker = ActivityWorker(browser_manager=mock_browser)
    return worker, mock_browser, mock_page


def _make_center(crawl_method="dynamic"):
    center = MagicMock()
    center.id = 42
    center.name = "테스트센터"
    center.crawl_method = crawl_method
    return center


def _common_patches(mock_crawler):
    """get_crawler/ImportService/SessionLocal 공통 patch 컨텍스트."""
    return (
        patch("app.modules.activity.crawlers.get_crawler", return_value=mock_crawler),
        patch("app.modules.activity.services.import_service.ImportService"),
        patch("app.worker.activity_worker.SessionLocal"),
    )


@pytest.mark.asyncio
async def test_dynamic_crawl_release_tab_R_normal():
    """R: 정상 crawl 완료 시 release_tab(page) 1회 호출 검증."""
    worker, mock_browser, mock_page = _make_worker()
    center = _make_center()

    mock_result = MagicMock()
    mock_result.status = "success"
    mock_result.error_message = None
    mock_crawler = AsyncMock()
    mock_crawler.crawl = AsyncMock(return_value=mock_result)

    with (
        patch("app.worker.activity_worker.ActivityWorker._ensure_browser_initialized", new_callable=AsyncMock),
        patch("app.modules.activity.crawlers.get_crawler", return_value=mock_crawler),
        patch("app.modules.activity.services.import_service.ImportService"),
        patch("app.worker.activity_worker.SessionLocal"),
    ):
        await worker._crawl_center(center, crawl_run_id=1)

    mock_browser.tab_pool_manager.get_tab.assert_called_once_with(
        target_id=center.id, service_account_id=None
    )
    mock_browser.tab_pool_manager.release_tab.assert_called_once_with(mock_page)


@pytest.mark.asyncio
async def test_dynamic_crawl_release_tab_E_crawl_exception():
    """E: crawler.crawl() 예외 시에도 finally에서 release_tab 호출 검증."""
    worker, mock_browser, mock_page = _make_worker()
    center = _make_center()

    mock_crawler = AsyncMock()
    mock_crawler.crawl = AsyncMock(side_effect=RuntimeError("크롤링 실패"))

    with (
        patch("app.worker.activity_worker.ActivityWorker._ensure_browser_initialized", new_callable=AsyncMock),
        patch("app.modules.activity.crawlers.get_crawler", return_value=mock_crawler),
        patch("app.modules.activity.services.import_service.ImportService"),
        patch("app.worker.activity_worker.SessionLocal"),
    ):
        with pytest.raises(RuntimeError):
            await worker._crawl_center(center, crawl_run_id=1)

    mock_browser.tab_pool_manager.release_tab.assert_called_once_with(mock_page)


@pytest.mark.asyncio
async def test_dynamic_crawl_release_tab_E_page_close_exception():
    """E: page.close() 예외 시에도 release_tab 호출 검증 (shield 효과)."""
    worker, mock_browser, mock_page = _make_worker()
    center = _make_center()
    mock_page.close = AsyncMock(side_effect=Exception("페이지 이미 닫힘"))

    mock_result = MagicMock()
    mock_result.status = "success"
    mock_result.error_message = None
    mock_crawler = AsyncMock()
    mock_crawler.crawl = AsyncMock(return_value=mock_result)

    with (
        patch("app.worker.activity_worker.ActivityWorker._ensure_browser_initialized", new_callable=AsyncMock),
        patch("app.modules.activity.crawlers.get_crawler", return_value=mock_crawler),
        patch("app.modules.activity.services.import_service.ImportService"),
        patch("app.worker.activity_worker.SessionLocal"),
    ):
        await worker._crawl_center(center, crawl_run_id=1)

    mock_browser.tab_pool_manager.release_tab.assert_called_once_with(mock_page)


@pytest.mark.asyncio
async def test_dynamic_crawl_release_tab_B_non_dynamic_skip():
    """B: crawl_method != 'dynamic'이면 get_tab/release_tab 호출 없음."""
    worker, mock_browser, _ = _make_worker()
    center = _make_center(crawl_method="static")

    mock_result = MagicMock()
    mock_result.status = "success"
    mock_result.error_message = None
    mock_crawler = AsyncMock()
    mock_crawler.crawl = AsyncMock(return_value=mock_result)

    with (
        patch("app.modules.activity.crawlers.get_crawler", return_value=mock_crawler),
        patch("app.modules.activity.services.import_service.ImportService"),
        patch("app.worker.activity_worker.SessionLocal"),
    ):
        await worker._crawl_center(center, crawl_run_id=1)

    mock_browser.tab_pool_manager.get_tab.assert_not_called()
    mock_browser.tab_pool_manager.release_tab.assert_not_called()


@pytest.mark.asyncio
async def test_dynamic_crawl_release_tab_B_browser_none():
    """B: worker.browser가 None이면 get_tab/release_tab 호출 없음 (분기 안전성).

    CrawlWorkerBase는 browser_manager=None 시 내부 생성하므로, 직접 None으로 패치.
    """
    from app.worker.activity_worker import ActivityWorker

    mock_browser = MagicMock()
    worker = ActivityWorker(browser_manager=mock_browser)
    worker.browser = None  # 직접 None으로 패치 — if self.browser: 분기 False
    center = _make_center()

    mock_result = MagicMock()
    mock_result.status = "success"
    mock_result.error_message = None
    mock_crawler = AsyncMock()
    mock_crawler.crawl = AsyncMock(return_value=mock_result)

    with (
        patch("app.modules.activity.crawlers.get_crawler", return_value=mock_crawler),
        patch("app.modules.activity.services.import_service.ImportService"),
        patch("app.worker.activity_worker.SessionLocal"),
    ):
        await worker._crawl_center(center, crawl_run_id=1)

    mock_browser.tab_pool_manager.get_tab.assert_not_called()
    mock_browser.tab_pool_manager.release_tab.assert_not_called()

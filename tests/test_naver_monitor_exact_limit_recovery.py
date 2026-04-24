"""
naver-monitor exact-limit orphan 재현/통합 TC (T3)

재현 시나리오:
- registered=1 탭 + non-blank orphan 4개 → actual_pages == TOTAL_MAX_TABS(5)
- `_cleanup_orphan_tabs()` 실행 시 orphan 4개 close, registered 탭 유지
- visible sentinel 탭은 orphan 판정에서 제외

실서버/Playwright 미사용. mock BrowserContext.pages 기반 in-process 검증.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

pytestmark = pytest.mark.integration


def _make_managed_page(tab_id: str, url: str = "https://booking.naver.com/1") -> MagicMock:
    page = MagicMock()
    page._tab_id = tab_id
    page.url = url
    page.close = AsyncMock()
    page.is_closed = MagicMock(return_value=False)
    return page


def _make_orphan_page(url: str = "https://booking.naver.com/orphan") -> MagicMock:
    """_tab_id가 없는 orphan 페이지 — pool 미등록."""
    page = MagicMock(spec=["url", "close", "is_closed"])
    page.url = url
    page.close = AsyncMock()
    page.is_closed = MagicMock(return_value=False)
    return page


@pytest.fixture
def tab_pool_manager_instance():
    from app.shared.browser.tab_pool_manager import TabPoolManager

    mock_cm = MagicMock()
    mock_cm.browser_contexts = {}
    manager = TabPoolManager(mock_cm)
    return manager


class TestExactLimitOrphanRecovery:
    """
    exact-limit(actual_pages == TOTAL_MAX_TABS) 상태에서 orphan cleanup → get_tab 복구 검증.
    """

    @pytest.mark.asyncio
    async def test_cleanup_removes_4_orphans_at_exact_limit(self, tab_pool_manager_instance):
        """
        registered=1 + non-blank orphan=4 → actual_pages==5(TOTAL_MAX_TABS).
        _cleanup_orphan_tabs() 호출 후 orphan 4개 close, registered 탭 close 미호출.
        """
        manager = tab_pool_manager_instance
        service_account_id = 1

        registered_page = _make_managed_page(tab_id="tab_1_0")
        orphans = [_make_orphan_page(url=f"https://booking.naver.com/orphan_{i}") for i in range(4)]

        all_pages = [registered_page] + orphans

        mock_context = MagicMock()
        mock_context.pages = all_pages

        # tab_pools에 registered 탭 등록
        manager.tab_pools[service_account_id] = {"tab_1_0": registered_page}
        manager.context_manager.browser_contexts = {service_account_id: mock_context}

        await manager._cleanup_orphan_tabs()

        registered_page.close.assert_not_awaited()
        for orphan in orphans:
            orphan.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_skips_visible_sentinel_at_exact_limit(self, tab_pool_manager_instance):
        """
        visible sentinel(_tab_id="visible_1") + non-blank orphan=4 → actual_pages==5.
        sentinel은 close 미호출, orphan 4개 close.
        """
        manager = tab_pool_manager_instance
        service_account_id = 1

        sentinel_page = _make_managed_page(tab_id="visible_1", url="https://booking.naver.com/sentinel")
        orphans = [_make_orphan_page(url=f"https://booking.naver.com/orphan_{i}") for i in range(4)]

        all_pages = [sentinel_page] + orphans
        mock_context = MagicMock()
        mock_context.pages = all_pages

        # sentinel은 tab_pools에 없음 (visible_ 접두사로 skip)
        manager.tab_pools[service_account_id] = {}
        manager.context_manager.browser_contexts = {service_account_id: mock_context}

        await manager._cleanup_orphan_tabs()

        sentinel_page.close.assert_not_awaited()
        for orphan in orphans:
            orphan.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_mixed_sentinel_and_registered_and_orphan(self, tab_pool_manager_instance):
        """
        registered=1 + visible sentinel=1 + orphan=3 → actual_pages==5.
        orphan 3개만 close됨.
        """
        manager = tab_pool_manager_instance
        service_account_id = 1

        registered_page = _make_managed_page(tab_id="tab_1_0")
        sentinel_page = _make_managed_page(tab_id="visible_1")
        orphans = [_make_orphan_page(url=f"https://nid.naver.com/page_{i}") for i in range(3)]

        all_pages = [registered_page, sentinel_page] + orphans
        mock_context = MagicMock()
        mock_context.pages = all_pages

        manager.tab_pools[service_account_id] = {"tab_1_0": registered_page}
        manager.context_manager.browser_contexts = {service_account_id: mock_context}

        await manager._cleanup_orphan_tabs()

        registered_page.close.assert_not_awaited()
        sentinel_page.close.assert_not_awaited()
        for orphan in orphans:
            orphan.close.assert_awaited_once()

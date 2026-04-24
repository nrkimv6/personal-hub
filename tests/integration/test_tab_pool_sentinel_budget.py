"""
T3 통합 TC: TabPoolManager sentinel 예산 분리 + login_check 정리 재현

근본 원인: get_tab() secondary gate가 visible sentinel을 예산에 포함해 cleanup=0건인
상태에서 영구 backoff 루프 발생.

수정 후 계약 검증:
1. sentinel 5개 상태에서 get_tab이 TimeoutError 없이 성공 (D3 fix)
2. pool+orphan 포화 시 cleanup이 orphan 정리 (혼합 포화 기존 동작 유지)
3. stale login_check 탭(31초+) → cleanup에서 close
4. 근래 login_check 탭(10초) → cleanup 후 보존
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# 테스트 픽스처 & 헬퍼
# ---------------------------------------------------------------------------

@pytest.fixture()
def pool_settings():
    """settings 패치 후 TabPoolManager 반환."""
    with patch('app.shared.browser.tab_pool_manager.settings') as ms:
        ms.TAB_ROTATION_THRESHOLD = 100
        ms.CACHE_CLEANUP_INTERVAL = 300
        ms.TAB_REQUEST_TIMEOUT = 5.0
        ms.TAB_WAIT_RETRY_INTERVAL = 0.05
        ms.TOTAL_MAX_TABS = 5
        ms.MAX_USES_PER_TAB = 50
        ms.TAB_CLEANUP_THRESHOLD = 3600
        from app.shared.browser.tab_pool_manager import TabPoolManager
        yield TabPoolManager, ms


def _make_page(tab_id=None, url="about:blank", is_closed=False):
    """TabPoolManager 내부 계약을 따르는 mock Page."""
    p = MagicMock()
    p.is_closed = MagicMock(return_value=is_closed)
    p.close = AsyncMock()
    p.url = url
    if tab_id is not None:
        p._tab_id = tab_id
    return p


# ---------------------------------------------------------------------------
# TC 1 — sentinel 포화 시 get_tab() 성공
# ---------------------------------------------------------------------------

class TestSentinelDoesNotStarveWorkerBudget:
    """D3 fix 검증: visible sentinel 탭이 worker 예산을 차지하지 않아야 함."""

    @pytest.mark.asyncio
    async def test_visible_sentinel_tabs_do_not_starve_worker_budget(self, pool_settings):
        """sentinel 5개 상태에서 pool에 빈 슬롯이 있으면 get_tab이 TimeoutError 없이 성공."""
        TabPoolManager, ms = pool_settings
        mock_cm = MagicMock()
        pool = TabPoolManager(mock_cm)
        pool.TOTAL_MAX_TABS = 5
        pool.TAB_REQUEST_TIMEOUT = 5.0
        pool.TAB_WAIT_RETRY_INTERVAL = 0.05

        # sentinel 5개 (사용자 가시 창)
        sentinels = [_make_page(tab_id=f"visible_{i}", url="https://naver.com") for i in range(5)]

        # context.pages = sentinel 5개 → budgeted_pages = 0
        mock_ctx = MagicMock()
        mock_ctx.pages = sentinels
        mock_ctx.browser = MagicMock()
        mock_ctx.browser.is_connected = MagicMock(return_value=True)

        # new_page()는 새 pool 탭 반환
        new_pool_page = MagicMock()
        new_pool_page._tab_id = "__pending__"
        new_pool_page.set_extra_http_headers = AsyncMock()
        mock_ctx.new_page = AsyncMock(return_value=new_pool_page)

        mock_cm.get_or_create_context = AsyncMock(return_value=mock_ctx)
        mock_cm.browser_contexts = {1: mock_ctx}
        mock_cm._get_context_lock = AsyncMock(return_value=asyncio.Lock())

        # pool은 비어 있음 (total_tabs = 0 < 5 → new_page 경로로 진입)
        pool.tab_pools[1] = {}

        tab = await asyncio.wait_for(
            pool.get_tab(target_id=999, service_account_id=1, inner_timeout=5.0),
            timeout=6.0,
        )

        assert tab is not None, "sentinel 5개 상태에서 get_tab이 TimeoutError를 발생시켜서는 안 됨"
        # 반환된 탭은 pool 탭이어야 함 (sentinel이 아님)
        assert getattr(tab, '_tab_id', None) != "visible_0"

    @pytest.mark.asyncio
    async def test_sentinel_5_plus_budgeted_0_allows_new_page(self, pool_settings):
        """sentinel 5개 + pool 0 → budgeted=0 → new_page 생성 경로 진입 확인."""
        TabPoolManager, ms = pool_settings
        mock_cm = MagicMock()
        pool = TabPoolManager(mock_cm)
        pool.TOTAL_MAX_TABS = 5
        pool.TAB_REQUEST_TIMEOUT = 3.0
        pool.TAB_WAIT_RETRY_INTERVAL = 0.05

        sentinels = [_make_page(tab_id=f"visible_{i}", url="https://booking.naver.com") for i in range(5)]
        new_tab_page = MagicMock()
        new_tab_page._tab_id = "__pending__"
        new_tab_page.set_extra_http_headers = AsyncMock()

        mock_ctx = MagicMock()
        mock_ctx.pages = sentinels
        mock_ctx.browser = MagicMock()
        mock_ctx.browser.is_connected = MagicMock(return_value=True)
        mock_ctx.new_page = AsyncMock(return_value=new_tab_page)

        mock_cm.get_or_create_context = AsyncMock(return_value=mock_ctx)
        mock_cm.browser_contexts = {1: mock_ctx}
        mock_cm._get_context_lock = AsyncMock(return_value=asyncio.Lock())
        pool.tab_pools[1] = {}

        tab = await pool.get_tab(target_id=1, service_account_id=1, inner_timeout=3.0)
        assert tab is not None

        # budgeted_pages = 0이므로 new_page가 호출됐어야 함
        mock_ctx.new_page.assert_called_once()


# ---------------------------------------------------------------------------
# TC 2 — 혼합 포화(pool + orphan) 시 cleanup이 orphan 정리
# ---------------------------------------------------------------------------

class TestMixedPoolOrphanPressure:
    """D3 fix에서 cleanup 조건(raw count)을 유지해 혼합 포화를 놓치지 않음을 검증."""

    @pytest.mark.asyncio
    async def test_mixed_pool_and_orphan_pressure_still_triggers_cleanup(self, pool_settings):
        """pool 4 + non-blank orphan 1 → cleanup이 orphan 정리, 예산 해방."""
        TabPoolManager, ms = pool_settings
        mock_cm = MagicMock()
        pool = TabPoolManager(mock_cm)
        pool.TOTAL_MAX_TABS = 5

        # pool 탭 4개
        pool_pages = [_make_page(tab_id=f"1_{i:04d}", url=f"https://naver.com/{i}") for i in range(4)]
        for i, p in enumerate(pool_pages):
            pool.tab_pools.setdefault(1, {})[f"1_{i:04d}"] = p
            pool.tab_pool[f"1_{i:04d}"] = p

        # non-blank orphan 1개 (about:blank가 아닌 URL)
        orphan = _make_page(url="https://booking.naver.com/stale", is_closed=False)

        mock_ctx = MagicMock()
        mock_ctx.pages = pool_pages + [orphan]
        pool.context_manager.browser_contexts = {1: mock_ctx}

        await pool._cleanup_orphan_tabs()

        # actual_pages_before = 5 >= TOTAL_MAX_TABS → orphan이 close 대상
        orphan.close.assert_awaited_once()
        for p in pool_pages:
            p.close.assert_not_awaited()


# ---------------------------------------------------------------------------
# TC 3 & 4 — stale / recent login_check 정리 재현
# ---------------------------------------------------------------------------

class TestLoginCheckCleanup:
    """D4 fix 검증: login_check 마커 탭의 cleanup 동작."""

    @pytest.mark.asyncio
    async def test_stale_login_check_closed_after_grace(self, pool_settings):
        """stale login_check(31초 경과) 탭이 cleanup에서 close됨."""
        TabPoolManager, ms = pool_settings
        mock_cm = MagicMock()
        pool = TabPoolManager(mock_cm)
        pool.TOTAL_MAX_TABS = 5

        old_ts = int(time.time()) - 31
        stale_lc = _make_page(
            tab_id=f"login_check_naver_1_{old_ts}",
            url="https://nid.naver.com/nidlogin.login",
        )

        mock_ctx = MagicMock()
        mock_ctx.pages = [stale_lc]
        pool.context_manager.browser_contexts = {1: mock_ctx}
        pool.tab_pools[1] = {}

        await pool._cleanup_orphan_tabs()
        stale_lc.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recent_login_check_preserved(self, pool_settings):
        """근래(10초 전) login_check 탭은 cleanup 후에도 close 미호출."""
        TabPoolManager, ms = pool_settings
        mock_cm = MagicMock()
        pool = TabPoolManager(mock_cm)
        pool.TOTAL_MAX_TABS = 5

        recent_ts = int(time.time()) - 10
        recent_lc = _make_page(
            tab_id=f"login_check_naver_1_{recent_ts}",
            url="https://www.naver.com",
        )

        mock_ctx = MagicMock()
        mock_ctx.pages = [recent_lc]
        pool.context_manager.browser_contexts = {1: mock_ctx}
        pool.tab_pools[1] = {}

        await pool._cleanup_orphan_tabs()
        recent_lc.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stale_and_sentinel_and_orphan_combined(self, pool_settings):
        """stale login_check + sentinel + orphan 조합 → login_check 정리, sentinel 보존, orphan close."""
        TabPoolManager, ms = pool_settings
        mock_cm = MagicMock()
        pool = TabPoolManager(mock_cm)
        pool.TOTAL_MAX_TABS = 5

        old_ts = int(time.time()) - 31
        stale_lc = _make_page(tab_id=f"login_check_naver_1_{old_ts}", url="https://naver.com")
        sentinel = _make_page(tab_id="visible_1", url="https://booking.naver.com")
        blank_orphan = _make_page(url="about:blank")

        mock_ctx = MagicMock()
        mock_ctx.pages = [stale_lc, sentinel, blank_orphan]
        pool.context_manager.browser_contexts = {1: mock_ctx}
        pool.tab_pools[1] = {}

        await pool._cleanup_orphan_tabs()

        stale_lc.close.assert_awaited_once()
        sentinel.close.assert_not_awaited()
        blank_orphan.close.assert_awaited_once()

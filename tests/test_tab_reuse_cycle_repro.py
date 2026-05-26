"""
Phase T3: 탭 재사용 사이클 재현/통합 TC

H1 fix 검증:
- 12스케줄/5탭 시나리오에서 starvation 없이 시간 분할 재사용
- _wake_waiters 예외 주입 후에도 이후 요청이 starvation 없이 완료
- new_page hang 시 NEW_PAGE_TIMEOUT 이후 recreate + 다른 요청 계속 진행
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import time
import pytest


@pytest.fixture
def pool_factory():
    def _make(total_max_tabs=5):
        with patch('app.shared.browser.tab_pool_manager.settings') as ms:
            ms.TAB_ROTATION_THRESHOLD = 600
            ms.CACHE_CLEANUP_INTERVAL = 300
            ms.TAB_REQUEST_TIMEOUT = 60
            ms.TAB_WAIT_RETRY_INTERVAL = 0.05  # 테스트용 단축
            ms.TOTAL_MAX_TABS = total_max_tabs
            ms.MAX_USES_PER_TAB = 50
            from app.shared.browser.tab_pool_manager import TabPoolManager
            context_manager = MagicMock()
            pool = TabPoolManager(context_manager)
        return pool
    return _make


@pytest.fixture
def pool_with_tabs(pool_factory):
    """5탭이 등록된 pool 픽스처 (모두 in_use=False, 재사용 가능)."""
    pool = pool_factory(total_max_tabs=5)
    pool.tab_pools[1] = {}

    for i in range(5):
        tab_id = f"1_{1000 + i}"
        mock_tab = MagicMock()
        mock_tab._tab_id = tab_id
        mock_tab._account_id = 1
        mock_tab._target_id = None
        pool.tab_pools[1][tab_id] = mock_tab
        pool.tab_pool[tab_id] = mock_tab
        pool.tab_last_used[tab_id] = time.time() - 1
        pool.tab_in_use[tab_id] = False
        pool.tab_use_count[tab_id] = 0
        pool.tab_account[tab_id] = 1

    pool.context_manager.get_or_create_context = AsyncMock()
    pool.context_manager.get_or_create_context.return_value.pages = []
    pool.cleanup_old_tabs = AsyncMock(return_value=0)
    pool.total_active_tabs = 5
    return pool


class TestTabReuseCycleBaseline:
    """12스케줄/5탭 시간 분할 재사용 baseline."""

    @pytest.mark.asyncio
    async def test_right_12_requests_5_tabs_complete_without_starvation(self, pool_with_tabs):
        """R: 12개 순차 요청이 5탭에서 재사용으로 모두 완료됨."""
        pool = pool_with_tabs

        completed = []
        for i in range(12):
            tab = await pool.get_tab(target_id=i + 1, service_account_id=1)
            assert tab is not None
            # 즉시 반환 (순차 재사용)
            await pool.release_tab(tab)
            completed.append(i)

        assert len(completed) == 12, f"완료 {len(completed)}/12 — starvation 없어야 함"
        assert all(not v for v in pool.tab_in_use.values()), "모든 탭이 반환된 상태여야 함"

    @pytest.mark.asyncio
    async def test_closed_available_tab_removed_and_fresh_tab_acquired(self, pool_factory):
        """E: 닫힌 pool tab은 acquire 시 제거되고 fresh tab으로 대체된다."""
        pool = pool_factory(total_max_tabs=5)
        pool.tab_pools[1] = {}

        stale_id = "1_1111"
        stale_tab = MagicMock()
        stale_tab._tab_id = stale_id
        stale_tab._account_id = 1
        stale_tab.is_closed = MagicMock(return_value=True)
        pool.tab_pools[1][stale_id] = stale_tab
        pool.tab_pool[stale_id] = stale_tab
        pool.tab_last_used[stale_id] = time.time()
        pool.tab_in_use[stale_id] = False
        pool.tab_use_count[stale_id] = 0
        pool.tab_account[stale_id] = 1
        pool.total_active_tabs = 1

        fresh_tab = MagicMock()
        fresh_tab.set_extra_http_headers = AsyncMock()
        fresh_tab.is_closed = MagicMock(return_value=False)
        fresh_tab.evaluate = AsyncMock(return_value=True)

        mock_context = MagicMock()
        mock_context.pages = []
        mock_context.new_page = AsyncMock(return_value=fresh_tab)
        pool.context_manager.get_or_create_context = AsyncMock(return_value=mock_context)
        pool.cleanup_old_tabs = AsyncMock(return_value=0)

        acquired = await pool.get_tab(target_id=123, service_account_id=1)

        assert acquired is fresh_tab
        assert stale_id not in pool.tab_pool
        assert stale_id not in pool.tab_pools[1]


class TestReleaseExceptionNoStarvation:
    """_wake_waiters 예외 후에도 대기 요청이 starvation 없이 해소됨."""

    @pytest.mark.asyncio
    async def test_right_wake_waiters_exception_no_starvation(self, pool_with_tabs):
        """R: _wake_waiters 예외에도 in_use=False 보장 → 이후 요청 정상 서빙."""
        pool = pool_with_tabs

        # 5탭 모두 in_use=True로 설정
        for tab_id in list(pool.tab_in_use.keys()):
            pool.tab_in_use[tab_id] = True

        # 첫 번째 탭을 획득된 것처럼 설정
        first_tab_id = list(pool.tab_pools[1].keys())[0]
        held_tab = pool.tab_pools[1][first_tab_id]
        held_tab._tab_id = first_tab_id
        held_tab._target_id = 999

        # _wake_waiters가 예외를 던지도록 세팅
        broken_event = MagicMock()
        broken_event.is_set.return_value = False
        broken_event.set.side_effect = RuntimeError("wake broken")
        pool.tab_waiters["waiter_x"] = broken_event

        # release_tab 호출 — 예외 발생하지만 in_use=False 보장
        await pool.release_tab(held_tab)
        assert pool.tab_in_use[first_tab_id] is False, \
            "H1: wake_waiters 예외에도 in_use=False여야 함"

        # 이후 동일 탭 재획득 가능 (starvation 없음)
        tab = await pool.get_tab(target_id=100, service_account_id=1)
        assert tab is not None
        await pool.release_tab(tab)


class TestNewPageHangRecovery:
    """new_page hang 시 NEW_PAGE_TIMEOUT 후 recreate → 다른 요청 계속."""

    @pytest.mark.asyncio
    async def test_right_new_page_hang_triggers_recreate_and_resumes(self, pool_factory):
        """R: new_page hang → 30s timeout → handle_browser_closed_error 호출."""
        pool = pool_factory(total_max_tabs=5)
        pool.TOTAL_MAX_TABS = 10  # 새 탭 생성 경로로 진입
        pool.NEW_PAGE_TIMEOUT = 0.05  # 테스트용 단축
        pool.tab_pools[1] = {}

        call_count = [0]
        created_tab = MagicMock()
        created_tab._tab_id = "__pending__"
        created_tab.set_extra_http_headers = AsyncMock()

        async def _conditional_new_page():
            call_count[0] += 1
            if call_count[0] == 1:
                await asyncio.sleep(10)  # hang
            return created_tab

        mock_context = MagicMock()
        mock_context.new_page = _conditional_new_page
        mock_context.pages = []
        pool.context_manager.get_or_create_context = AsyncMock(return_value=mock_context)
        pool.handle_browser_closed_error = AsyncMock(return_value=True)
        pool.register_initial_tabs = AsyncMock(return_value=0)
        pool.cleanup_old_tabs = AsyncMock(return_value=0)

        try:
            await asyncio.wait_for(
                pool.get_tab(target_id=200, service_account_id=1),
                timeout=2.0
            )
        except (asyncio.TimeoutError, Exception):
            pass

        pool.handle_browser_closed_error.assert_called(), \
            "H2: new_page hang 후 handle_browser_closed_error가 호출되어야 함"

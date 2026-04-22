"""
TabPoolManager 테스트

경로: app/shared/browser/tab_pool_manager.py

RIGHT-BICEP 패턴:
- Right: 정상 동작 테스트
- Boundary: 경계값 테스트
- Inverse: 역관계 테스트
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 특성 테스트
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import time


class TestTabPoolManagerInit:
    """TabPoolManager 초기화 테스트"""

    def test_right_init_with_context_manager(self):
        """ContextManager와 함께 초기화"""
        with patch('app.shared.browser.tab_pool_manager.settings') as mock_settings:
            mock_settings.TAB_ROTATION_THRESHOLD = 100
            mock_settings.CACHE_CLEANUP_INTERVAL = 300
            mock_settings.TAB_REQUEST_TIMEOUT = 30
            mock_settings.TAB_WAIT_RETRY_INTERVAL = 0.5
            mock_settings.TOTAL_MAX_TABS = 10
            mock_settings.MAX_USES_PER_TAB = 50

            from app.shared.browser.tab_pool_manager import TabPoolManager

            mock_context_manager = MagicMock()
            pool = TabPoolManager(mock_context_manager)

            assert pool.context_manager == mock_context_manager
            assert pool.tab_pools == {}
            assert pool.total_active_tabs == 0

    def test_right_init_sets_default_configs(self):
        """기본 설정값 적용 확인"""
        with patch('app.shared.browser.tab_pool_manager.settings') as mock_settings:
            mock_settings.TAB_ROTATION_THRESHOLD = 100
            mock_settings.CACHE_CLEANUP_INTERVAL = 300
            mock_settings.TAB_REQUEST_TIMEOUT = 30
            mock_settings.TAB_WAIT_RETRY_INTERVAL = 0.5
            mock_settings.TOTAL_MAX_TABS = 10
            mock_settings.MAX_USES_PER_TAB = 50

            from app.shared.browser.tab_pool_manager import TabPoolManager

            mock_context_manager = MagicMock()
            pool = TabPoolManager(mock_context_manager)

            assert pool.TAB_ROTATION_THRESHOLD == 100
            assert pool.TOTAL_MAX_TABS == 10
            assert pool.MAX_USES_PER_TAB == 50


class TestGetPoolSize:
    """get_pool_size 메서드 테스트"""

    @pytest.fixture
    def tab_pool_manager(self):
        """테스트용 TabPoolManager 인스턴스"""
        with patch('app.shared.browser.tab_pool_manager.settings') as mock_settings:
            mock_settings.TAB_ROTATION_THRESHOLD = 100
            mock_settings.CACHE_CLEANUP_INTERVAL = 300
            mock_settings.TAB_REQUEST_TIMEOUT = 30
            mock_settings.TAB_WAIT_RETRY_INTERVAL = 0.5
            mock_settings.TOTAL_MAX_TABS = 10
            mock_settings.MAX_USES_PER_TAB = 50

            from app.shared.browser.tab_pool_manager import TabPoolManager

            mock_context_manager = MagicMock()
            return TabPoolManager(mock_context_manager)

    def test_right_empty_pool_returns_zero(self, tab_pool_manager):
        """빈 풀은 0 반환"""
        assert tab_pool_manager.get_pool_size() == 0

    def test_right_counts_tabs_for_specific_account(self, tab_pool_manager):
        """특정 계정의 탭 수 반환"""
        tab_pool_manager.tab_pools[1] = {"tab_1": MagicMock(), "tab_2": MagicMock()}
        tab_pool_manager.tab_pools[2] = {"tab_3": MagicMock()}

        assert tab_pool_manager.get_pool_size(service_account_id=1) == 2
        assert tab_pool_manager.get_pool_size(service_account_id=2) == 1

    def test_right_counts_all_tabs_when_no_account_specified(self, tab_pool_manager):
        """계정 지정 없으면 전체 탭 수 반환"""
        tab_pool_manager.tab_pools[1] = {"tab_1": MagicMock(), "tab_2": MagicMock()}
        tab_pool_manager.tab_pools[2] = {"tab_3": MagicMock()}

        assert tab_pool_manager.get_pool_size() == 3

    def test_boundary_nonexistent_account_returns_zero(self, tab_pool_manager):
        """존재하지 않는 계정은 0 반환"""
        assert tab_pool_manager.get_pool_size(service_account_id=999) == 0


class TestReleaseTab:
    """release_tab 메서드 테스트"""

    @pytest.fixture
    def tab_pool_manager(self):
        """테스트용 TabPoolManager 인스턴스"""
        with patch('app.shared.browser.tab_pool_manager.settings') as mock_settings:
            mock_settings.TAB_ROTATION_THRESHOLD = 100
            mock_settings.CACHE_CLEANUP_INTERVAL = 300
            mock_settings.TAB_REQUEST_TIMEOUT = 30
            mock_settings.TAB_WAIT_RETRY_INTERVAL = 0.5
            mock_settings.TOTAL_MAX_TABS = 10
            mock_settings.MAX_USES_PER_TAB = 50

            from app.shared.browser.tab_pool_manager import TabPoolManager

            mock_context_manager = MagicMock()
            return TabPoolManager(mock_context_manager)

    @pytest.mark.asyncio
    async def test_right_release_marks_tab_not_in_use(self, tab_pool_manager):
        """탭 반환 시 사용 중 플래그 해제"""
        mock_tab = MagicMock()
        mock_tab._tab_id = "tab_1"

        tab_pool_manager.tab_in_use["tab_1"] = True
        tab_pool_manager.tab_account["tab_1"] = 1
        tab_pool_manager.tab_current_target["tab_1"] = 100

        await tab_pool_manager.release_tab(mock_tab)

        assert tab_pool_manager.tab_in_use["tab_1"] is False
        assert "tab_1" not in tab_pool_manager.tab_current_target

    @pytest.mark.asyncio
    async def test_right_release_updates_last_used_time(self, tab_pool_manager):
        """탭 반환 시 마지막 사용 시간 업데이트"""
        mock_tab = MagicMock()
        mock_tab._tab_id = "tab_1"

        tab_pool_manager.tab_in_use["tab_1"] = True
        tab_pool_manager.tab_account["tab_1"] = 1

        await tab_pool_manager.release_tab(mock_tab)

        assert "tab_1" in tab_pool_manager.tab_last_used

    @pytest.mark.asyncio
    async def test_boundary_release_nonexistent_tab(self, tab_pool_manager):
        """존재하지 않는 탭 반환 시 에러 없음"""
        mock_tab = MagicMock()
        mock_tab._tab_id = "nonexistent_tab"

        # 에러 없이 처리되어야 함
        await tab_pool_manager.release_tab(mock_tab)


class TestCloseAllTabs:
    """close_all_tabs 메서드 테스트"""

    @pytest.fixture
    def tab_pool_manager(self):
        """테스트용 TabPoolManager 인스턴스"""
        with patch('app.shared.browser.tab_pool_manager.settings') as mock_settings:
            mock_settings.TAB_ROTATION_THRESHOLD = 100
            mock_settings.CACHE_CLEANUP_INTERVAL = 300
            mock_settings.TAB_REQUEST_TIMEOUT = 30
            mock_settings.TAB_WAIT_RETRY_INTERVAL = 0.5
            mock_settings.TOTAL_MAX_TABS = 10
            mock_settings.MAX_USES_PER_TAB = 50

            from app.shared.browser.tab_pool_manager import TabPoolManager

            mock_context_manager = MagicMock()
            return TabPoolManager(mock_context_manager)

    @pytest.mark.asyncio
    async def test_right_closes_all_tabs(self, tab_pool_manager):
        """모든 탭 닫기"""
        mock_tab1 = MagicMock()
        mock_tab1._tab_id = "tab_1"
        mock_tab1.is_closed = MagicMock(return_value=False)
        mock_tab1.close = AsyncMock()

        mock_tab2 = MagicMock()
        mock_tab2._tab_id = "tab_2"
        mock_tab2.is_closed = MagicMock(return_value=False)
        mock_tab2.close = AsyncMock()

        tab_pool_manager.tab_pools[1] = {"tab_1": mock_tab1, "tab_2": mock_tab2}
        tab_pool_manager.tab_account["tab_1"] = 1
        tab_pool_manager.tab_account["tab_2"] = 1

        closed_count = await tab_pool_manager.close_all_tabs()

        assert closed_count == 2
        mock_tab1.close.assert_called_once()
        mock_tab2.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_right_clears_pool_after_close(self, tab_pool_manager):
        """닫은 후 풀 정리"""
        mock_tab = MagicMock()
        mock_tab._tab_id = "tab_1"
        mock_tab.is_closed = MagicMock(return_value=False)
        mock_tab.close = AsyncMock()

        tab_pool_manager.tab_pools[1] = {"tab_1": mock_tab}
        tab_pool_manager.tab_account["tab_1"] = 1
        tab_pool_manager.tab_in_use["tab_1"] = False
        tab_pool_manager.tab_use_count["tab_1"] = 5

        await tab_pool_manager.close_all_tabs()

        assert tab_pool_manager.tab_pools[1] == {}

    @pytest.mark.asyncio
    async def test_boundary_empty_pool_returns_zero(self, tab_pool_manager):
        """빈 풀은 0 반환"""
        closed_count = await tab_pool_manager.close_all_tabs()
        assert closed_count == 0


class TestHandleBrowserClosedError:
    """handle_browser_closed_error 메서드 테스트"""

    @pytest.fixture
    def tab_pool_manager(self):
        """테스트용 TabPoolManager 인스턴스"""
        with patch('app.shared.browser.tab_pool_manager.settings') as mock_settings:
            mock_settings.TAB_ROTATION_THRESHOLD = 100
            mock_settings.CACHE_CLEANUP_INTERVAL = 300
            mock_settings.TAB_REQUEST_TIMEOUT = 30
            mock_settings.TAB_WAIT_RETRY_INTERVAL = 0.5
            mock_settings.TOTAL_MAX_TABS = 10
            mock_settings.MAX_USES_PER_TAB = 50

            from app.shared.browser.tab_pool_manager import TabPoolManager

            mock_context_manager = MagicMock()
            mock_context_manager.close_context = AsyncMock()
            mock_context_manager.get_or_create_context = AsyncMock()
            mock_context_manager._get_context_lock = AsyncMock(return_value=asyncio.Lock())
            return TabPoolManager(mock_context_manager)

    @pytest.mark.asyncio
    async def test_right_cleans_up_account_tabs(self, tab_pool_manager):
        """계정별 탭 정리"""
        mock_tab = MagicMock()
        mock_tab._tab_id = "tab_1"

        tab_pool_manager.tab_pools[1] = {"tab_1": mock_tab}
        tab_pool_manager.tab_account["tab_1"] = 1
        tab_pool_manager.tab_in_use["tab_1"] = True

        result = await tab_pool_manager.handle_browser_closed_error(1, recreate=False)

        assert result is True
        assert 1 not in tab_pool_manager.tab_pools or tab_pool_manager.tab_pools[1] == {}

    @pytest.mark.asyncio
    async def test_right_prevents_race_condition(self, tab_pool_manager):
        """동시 복구 시도 방지"""
        tab_pool_manager._recovery_in_progress[1] = True

        result = await tab_pool_manager.handle_browser_closed_error(1, recreate=True)

        # 이미 복구 중이면 False 반환
        assert result is False


class TestIsTabClosed:
    """_is_tab_closed 메서드 테스트"""

    @pytest.fixture
    def tab_pool_manager(self):
        """테스트용 TabPoolManager 인스턴스"""
        with patch('app.shared.browser.tab_pool_manager.settings') as mock_settings:
            mock_settings.TAB_ROTATION_THRESHOLD = 100
            mock_settings.CACHE_CLEANUP_INTERVAL = 300
            mock_settings.TAB_REQUEST_TIMEOUT = 30
            mock_settings.TAB_WAIT_RETRY_INTERVAL = 0.5
            mock_settings.TOTAL_MAX_TABS = 10
            mock_settings.MAX_USES_PER_TAB = 50

            from app.shared.browser.tab_pool_manager import TabPoolManager

            mock_context_manager = MagicMock()
            return TabPoolManager(mock_context_manager)

    @pytest.mark.asyncio
    async def test_right_detects_closed_tab(self, tab_pool_manager):
        """닫힌 탭 감지 (is_closed가 True 반환)"""
        mock_tab = MagicMock()
        mock_tab.is_closed = MagicMock(return_value=True)

        result = await tab_pool_manager._is_tab_closed(mock_tab)
        assert result is True

    @pytest.mark.asyncio
    async def test_right_detects_open_tab(self, tab_pool_manager):
        """열린 탭 감지 (is_closed가 False이고 evaluate 성공)"""
        mock_tab = MagicMock()
        mock_tab.is_closed = MagicMock(return_value=False)
        mock_tab.evaluate = AsyncMock(return_value=True)

        result = await tab_pool_manager._is_tab_closed(mock_tab)
        assert result is False

    @pytest.mark.asyncio
    async def test_error_exception_returns_true(self, tab_pool_manager):
        """예외 발생 시 닫힌 것으로 처리"""
        mock_tab = MagicMock()
        mock_tab.is_closed = MagicMock(side_effect=Exception("Connection lost"))

        result = await tab_pool_manager._is_tab_closed(mock_tab)
        assert result is True

    @pytest.mark.asyncio
    async def test_error_evaluate_failure_returns_true(self, tab_pool_manager):
        """evaluate 실패 시 닫힌 것으로 처리"""
        mock_tab = MagicMock()
        mock_tab.is_closed = MagicMock(return_value=False)
        mock_tab.evaluate = AsyncMock(side_effect=Exception("Page crashed"))

        result = await tab_pool_manager._is_tab_closed(mock_tab)
        assert result is True


class TestTabTrackingState:
    """탭 추적 상태 관리 테스트"""

    @pytest.fixture
    def tab_pool_manager(self):
        """테스트용 TabPoolManager 인스턴스"""
        with patch('app.shared.browser.tab_pool_manager.settings') as mock_settings:
            mock_settings.TAB_ROTATION_THRESHOLD = 100
            mock_settings.CACHE_CLEANUP_INTERVAL = 300
            mock_settings.TAB_REQUEST_TIMEOUT = 30
            mock_settings.TAB_WAIT_RETRY_INTERVAL = 0.5
            mock_settings.TOTAL_MAX_TABS = 10
            mock_settings.MAX_USES_PER_TAB = 50

            from app.shared.browser.tab_pool_manager import TabPoolManager

            mock_context_manager = MagicMock()
            return TabPoolManager(mock_context_manager)

    def test_right_tab_use_count_tracking(self, tab_pool_manager):
        """탭 사용 횟수 추적"""
        tab_pool_manager.tab_use_count["tab_1"] = 0
        tab_pool_manager.tab_use_count["tab_1"] += 1

        assert tab_pool_manager.tab_use_count["tab_1"] == 1

    def test_right_tab_in_use_flag(self, tab_pool_manager):
        """탭 사용 중 플래그"""
        tab_pool_manager.tab_in_use["tab_1"] = True
        assert tab_pool_manager.tab_in_use["tab_1"] is True

        tab_pool_manager.tab_in_use["tab_1"] = False
        assert tab_pool_manager.tab_in_use["tab_1"] is False

    def test_right_tab_account_mapping(self, tab_pool_manager):
        """탭-계정 매핑"""
        tab_pool_manager.tab_account["tab_1"] = 1
        tab_pool_manager.tab_account["tab_2"] = 2

        assert tab_pool_manager.tab_account["tab_1"] == 1
        assert tab_pool_manager.tab_account["tab_2"] == 2

    def test_right_multiple_accounts_isolation(self, tab_pool_manager):
        """계정별 탭 풀 격리"""
        tab_pool_manager.tab_pools[1] = {"tab_1": MagicMock()}
        tab_pool_manager.tab_pools[2] = {"tab_2": MagicMock()}

        assert "tab_1" in tab_pool_manager.tab_pools[1]
        assert "tab_1" not in tab_pool_manager.tab_pools[2]
        assert "tab_2" in tab_pool_manager.tab_pools[2]
        assert "tab_2" not in tab_pool_manager.tab_pools[1]


# ---------------------------------------------------------------------------
# 신규 TC (Phase T1): D1 waiter 누수, D2 dead waiter starvation, D5 orphan,
#                     get_status(), _wake_waiters()
# ---------------------------------------------------------------------------

@pytest.fixture()
def make_pool():
    """TabPoolManager 팩토리 (설정 패치 포함)"""
    def _factory(total_max_tabs=5, tab_wait_retry_interval=0.05, tab_request_timeout=0.5):
        with patch('app.shared.browser.tab_pool_manager.settings') as mock_settings:
            mock_settings.TAB_ROTATION_THRESHOLD = 100
            mock_settings.CACHE_CLEANUP_INTERVAL = 300
            mock_settings.TAB_REQUEST_TIMEOUT = tab_request_timeout
            mock_settings.TAB_WAIT_RETRY_INTERVAL = tab_wait_retry_interval
            mock_settings.TOTAL_MAX_TABS = total_max_tabs
            mock_settings.MAX_USES_PER_TAB = 50
            mock_settings.TAB_CLEANUP_THRESHOLD = 3600

            from app.shared.browser.tab_pool_manager import TabPoolManager
            return TabPoolManager(MagicMock())
    return _factory


class TestTabPoolManagerStatus:
    """get_status() 메서드 + _wake_waiters() 헬퍼 TC"""

    def test_right_get_status_empty_pool(self, make_pool):
        """`get_status()` — 빈 풀에서 모든 카운터가 0"""
        pool = make_pool()
        status = pool.get_status()
        assert status["total_active_tabs"] == 0
        assert status["in_use_count"] == 0
        assert status["waiter_count"] == 0
        assert status["dead_waiter_count"] == 0
        assert status["account_pool_sizes"] == {}

    def test_right_get_status_counts_waiters_and_dead_waiters(self, make_pool):
        """`get_status()` — live/dead waiter 수, in_use_count, account_pool_sizes 집계"""
        pool = make_pool()
        # 탭 2개 등록 (1개 사용중)
        pool.tab_pools[1] = {"t1": MagicMock(), "t2": MagicMock()}
        pool.tab_in_use["t1"] = True
        pool.tab_in_use["t2"] = False
        # live waiter 1개, dead waiter 1개 (is_set=True)
        live_ev = asyncio.Event()
        dead_ev = asyncio.Event()
        dead_ev.set()
        pool.tab_waiters["r1"] = live_ev
        pool.tab_waiters["r2"] = dead_ev

        status = pool.get_status()
        assert status["total_active_tabs"] == 2
        assert status["in_use_count"] == 1
        assert status["waiter_count"] == 2
        assert status["dead_waiter_count"] == 1
        assert status["account_pool_sizes"] == {1: 2}

    def test_cross_wake_waiters_one_skips_dead_returns_live(self, make_pool):
        """`_wake_waiters(one)` — dead waiter 건너뛰고 live 1개만 깨움"""
        pool = make_pool()
        dead_ev = asyncio.Event()
        dead_ev.set()
        live_ev = asyncio.Event()
        pool.tab_waiters["dead"] = dead_ev
        pool.tab_waiters["live"] = live_ev

        woken, dead_cleaned = pool._wake_waiters(strategy="one")

        assert dead_cleaned == 1
        assert woken == 1
        assert live_ev.is_set()
        assert pool.tab_waiters == {}

    def test_cross_wake_waiters_all_wakes_all_live(self, make_pool):
        """`_wake_waiters(all)` — 모든 live waiter 깨움"""
        pool = make_pool()
        ev1 = asyncio.Event()
        ev2 = asyncio.Event()
        dead_ev = asyncio.Event()
        dead_ev.set()
        pool.tab_waiters["r1"] = ev1
        pool.tab_waiters["r2"] = ev2
        pool.tab_waiters["dead"] = dead_ev

        woken, dead_cleaned = pool._wake_waiters(strategy="all")

        assert dead_cleaned == 1
        assert woken == 2
        assert ev1.is_set()
        assert ev2.is_set()
        assert pool.tab_waiters == {}


class TestTabPoolManagerWaiterLeak:
    """D1: outer cancel 시 waiter dict 정리 TC"""

    @pytest.mark.asyncio
    async def test_error_outer_cancel_does_not_leak_waiter(self, make_pool):
        """`wait_for(get_tab(...), timeout=짧은값)` 취소 후 tab_waiters == {}"""
        pool = make_pool(total_max_tabs=1, tab_wait_retry_interval=10.0, tab_request_timeout=30.0)

        # 풀을 가득 채워 모든 탭이 사용 중이 되게 만듦
        mock_tab = MagicMock()
        mock_tab.is_closed = MagicMock(return_value=False)
        mock_tab.evaluate = AsyncMock(return_value=True)
        pool.tab_pools[1] = {"t1": mock_tab}
        pool.tab_in_use["t1"] = True
        pool.tab_account["t1"] = 1
        pool.tab_use_count["t1"] = 0
        pool.tab_last_used["t1"] = 0.0
        pool.total_active_tabs = 1

        mock_ctx = MagicMock()
        mock_ctx.pages = [mock_tab]
        mock_ctx.browser = MagicMock()
        mock_ctx.browser.is_connected = MagicMock(return_value=True)
        pool.context_manager.get_or_create_context = AsyncMock(return_value=mock_ctx)
        pool.context_manager.browser_contexts = {}
        pool.context_manager._get_context_lock = AsyncMock(return_value=asyncio.Lock())

        # 아주 짧은 outer timeout으로 강제 취소
        with pytest.raises((asyncio.TimeoutError, Exception)):
            await asyncio.wait_for(
                pool.get_tab(target_id=99, service_account_id=1),
                timeout=0.05
            )

        assert pool.tab_waiters == {}, f"waiter 누수: {pool.tab_waiters}"

    @pytest.mark.asyncio
    async def test_error_multiple_outer_cancels_no_accumulation(self, make_pool):
        """같은 시나리오 5회 반복 후에도 waiter dict 길이가 0"""
        pool = make_pool(total_max_tabs=1, tab_wait_retry_interval=10.0, tab_request_timeout=30.0)

        mock_tab = MagicMock()
        mock_tab.is_closed = MagicMock(return_value=False)
        mock_tab.evaluate = AsyncMock(return_value=True)
        pool.tab_pools[1] = {"t1": mock_tab}
        pool.tab_in_use["t1"] = True
        pool.tab_account["t1"] = 1
        pool.tab_use_count["t1"] = 0
        pool.tab_last_used["t1"] = 0.0
        pool.total_active_tabs = 1

        mock_ctx = MagicMock()
        mock_ctx.pages = [mock_tab]
        mock_ctx.browser = MagicMock()
        mock_ctx.browser.is_connected = MagicMock(return_value=True)
        pool.context_manager.get_or_create_context = AsyncMock(return_value=mock_ctx)
        pool.context_manager.browser_contexts = {}
        pool.context_manager._get_context_lock = AsyncMock(return_value=asyncio.Lock())

        for _ in range(5):
            with pytest.raises(Exception):
                await asyncio.wait_for(
                    pool.get_tab(target_id=99, service_account_id=1),
                    timeout=0.05
                )

        assert len(pool.tab_waiters) == 0, f"waiter 누적: {len(pool.tab_waiters)}"


class TestTabPoolManagerReleaseTabFairness:
    """D2: dead waiter 회피 + 공정성 TC"""

    @pytest.mark.asyncio
    async def test_cross_skips_dead_waiter_and_wakes_live(self, make_pool):
        """dead waiter를 건너뛰고 live waiter 1건만 깨우는지 검증"""
        pool = make_pool()
        mock_tab = MagicMock()
        mock_tab._tab_id = "t1"
        pool.tab_in_use["t1"] = True
        pool.tab_account["t1"] = 1
        pool.tab_current_target["t1"] = 10
        pool.tab_last_used["t1"] = 0.0

        dead_ev = asyncio.Event()
        dead_ev.set()
        live_ev = asyncio.Event()
        pool.tab_waiters["dead"] = dead_ev
        pool.tab_waiters["live"] = live_ev

        await pool.release_tab(mock_tab)

        assert live_ev.is_set(), "live waiter가 깨워지지 않음"
        assert pool.tab_waiters == {}, f"waiter 잔류: {pool.tab_waiters}"

    @pytest.mark.asyncio
    async def test_cross_only_one_live_waiter_woken_per_release(self, make_pool):
        """release 1회당 live waiter 1명만 깨어나는지 검증"""
        pool = make_pool()
        mock_tab = MagicMock()
        mock_tab._tab_id = "t1"
        pool.tab_in_use["t1"] = True
        pool.tab_account["t1"] = 1
        pool.tab_last_used["t1"] = 0.0

        ev1 = asyncio.Event()
        ev2 = asyncio.Event()
        pool.tab_waiters["r1"] = ev1
        pool.tab_waiters["r2"] = ev2

        await pool.release_tab(mock_tab)

        woken = sum(1 for ev in [ev1, ev2] if ev.is_set())
        assert woken == 1, f"release 1회에 {woken}개 깨어남"


class TestTabPoolManagerOrphanOnCancel:
    """D5: new_page() cancel 시 미등록 탭 정리 TC"""

    @pytest.mark.asyncio
    async def test_error_header_setup_failure_closes_unregistered_tab(self, make_pool):
        """`set_extra_http_headers()` 실패 시 미등록 탭이 닫히는지 검증"""
        pool = make_pool(total_max_tabs=5)

        mock_page = AsyncMock()
        mock_page.set_extra_http_headers = AsyncMock(side_effect=Exception("header error"))
        mock_page.close = AsyncMock()

        mock_ctx = MagicMock()
        mock_ctx.pages = []
        mock_ctx.browser = MagicMock()
        mock_ctx.browser.is_connected = MagicMock(return_value=True)
        mock_ctx.new_page = AsyncMock(return_value=mock_page)
        pool.context_manager.get_or_create_context = AsyncMock(return_value=mock_ctx)
        pool.context_manager.browser_contexts = {}
        pool.context_manager._get_context_lock = AsyncMock(return_value=asyncio.Lock())

        # 계정 탭 풀 빈 상태 (새 탭 생성 경로로 진입)
        pool.tab_pools[1] = {}
        pool.total_active_tabs = 0

        with pytest.raises(Exception):
            await pool.get_tab(target_id=1, service_account_id=1)

        # 미등록 탭은 반드시 close() 호출되어야 함
        mock_page.close.assert_called_once()


class TestTabPoolManagerConcurrentRepro:
    """Phase T3: 실제 asyncio 스케줄링으로 contention/cancel race 재현"""

    @pytest.mark.asyncio
    async def test_concurrent_acquire_waiter_dict_drains_after_all_done(self, make_pool):
        """TOTAL_MAX_TABS=2, 요청 4개 (outer cancel 2개) 종료 후 tab_waiters == {}"""
        pool = make_pool(total_max_tabs=2, tab_wait_retry_interval=0.02, tab_request_timeout=5.0)

        # 탭 풀: 2개 탭 미리 채움
        pages = []
        for i in range(2):
            p = AsyncMock()
            p._tab_id = f"t{i}"
            p.is_closed = MagicMock(return_value=False)
            p.evaluate = AsyncMock(return_value=True)
            pool.tab_pools[1] = pool.tab_pools.get(1, {})
            pool.tab_pools[1][f"t{i}"] = p
            pool.tab_in_use[f"t{i}"] = False
            pool.tab_account[f"t{i}"] = 1
            pool.tab_use_count[f"t{i}"] = 0
            pool.tab_last_used[f"t{i}"] = 0.0
            pages.append(p)
        pool.total_active_tabs = 2

        mock_ctx = MagicMock()
        mock_ctx.pages = pages
        mock_ctx.browser = MagicMock()
        mock_ctx.browser.is_connected = MagicMock(return_value=True)
        pool.context_manager.get_or_create_context = AsyncMock(return_value=mock_ctx)
        pool.context_manager.browser_contexts = {}
        pool.context_manager._get_context_lock = AsyncMock(return_value=asyncio.Lock())

        acquired = []
        released = asyncio.Event()

        async def acquire_and_hold(req_id: int):
            tab = await pool.get_tab(target_id=req_id, service_account_id=1)
            acquired.append(req_id)
            await asyncio.sleep(0.05)  # 잠깐 사용
            await pool.release_tab(tab)

        # 2개는 정상 acquire, 2개는 대기 → cancel
        tasks = [asyncio.create_task(acquire_and_hold(i)) for i in range(4)]
        await asyncio.sleep(0.01)  # 일부 waiter 등록 대기

        # 대기 중인 태스크 2개 취소
        for t in tasks[2:]:
            t.cancel()

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 완료 후 waiter dict가 비어 있어야 함
        assert pool.tab_waiters == {}, f"waiter 잔류: {pool.tab_waiters}"

    @pytest.mark.asyncio
    async def test_concurrent_acquire_with_outer_cancels_no_starvation(self, make_pool):
        """TOTAL_MAX_TABS=5, 요청 8개 중 2개 outer cancel → 나머지 6개 starvation 없이 완료"""
        pool = make_pool(total_max_tabs=5, tab_wait_retry_interval=0.02, tab_request_timeout=5.0)

        # 탭 풀: 5개 탭 미리 채움. tab_last_used=time.time()으로 cleanup_old_tabs 유발 방지
        now = time.time()
        for i in range(5):
            tab_id = f"t{i}"
            p = AsyncMock()
            p._tab_id = tab_id
            p.is_closed = MagicMock(return_value=False)
            p.evaluate = AsyncMock(return_value=True)
            pool.tab_pools[1] = pool.tab_pools.get(1, {})
            pool.tab_pools[1][tab_id] = p
            pool.tab_in_use[tab_id] = False
            pool.tab_account[tab_id] = 1
            pool.tab_use_count[tab_id] = 0
            pool.tab_last_used[tab_id] = now  # stale 방지
        pool.total_active_tabs = 5

        mock_ctx = MagicMock()
        mock_ctx.pages = list(pool.tab_pools[1].values())
        mock_ctx.browser = MagicMock()
        mock_ctx.browser.is_connected = MagicMock(return_value=True)
        pool.context_manager.get_or_create_context = AsyncMock(return_value=mock_ctx)
        pool.context_manager.browser_contexts = {}
        pool.context_manager._get_context_lock = AsyncMock(return_value=asyncio.Lock())

        completed = []

        async def acquire_and_hold(req_id: int):
            tab = await pool.get_tab(target_id=req_id, service_account_id=1)
            await asyncio.sleep(0.04)
            await pool.release_tab(tab)
            completed.append(req_id)

        # 8개 태스크: 0-4는 즉시 acquire, 5-7은 waiter 큐에서 대기
        tasks = [asyncio.create_task(acquire_and_hold(i)) for i in range(8)]
        await asyncio.sleep(0.01)  # waiter 등록 대기

        # 태스크 5, 6 취소 (waiter 큐에 있는 것들)
        tasks[5].cancel()
        tasks[6].cancel()

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 6개(0-4, 7)가 CancelledError 없이 완료
        cancelled_count = sum(1 for r in results if isinstance(r, asyncio.CancelledError))
        assert cancelled_count == 2, f"취소 수 불일치: {cancelled_count}"
        assert len(completed) == 6, f"starvation 의심: completed={completed}"
        assert pool.tab_waiters == {}, f"waiter 잔류: {pool.tab_waiters}"

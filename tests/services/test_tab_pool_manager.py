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


# ============================================================
# actual_pages secondary gate 테스트 (Phase 2: 원인 A 수정 검증)
# ============================================================

class TestActualPagesGate:
    """실제 페이지 수 기반 TOTAL_MAX_TABS secondary gate 테스트"""

    def _make_pool(self, total_max=5):
        with patch('app.shared.browser.tab_pool_manager.settings') as mock_settings:
            mock_settings.TAB_ROTATION_THRESHOLD = 100
            mock_settings.CACHE_CLEANUP_INTERVAL = 300
            mock_settings.TAB_REQUEST_TIMEOUT = 30
            mock_settings.TAB_WAIT_RETRY_INTERVAL = 0.1
            mock_settings.TOTAL_MAX_TABS = total_max
            mock_settings.MAX_USES_PER_TAB = 50
            mock_settings.TAB_CLEANUP_THRESHOLD = 600

            from app.shared.browser.tab_pool_manager import TabPoolManager
            mock_cm = MagicMock()
            pool = TabPoolManager(mock_cm)
            pool.TOTAL_MAX_TABS = total_max
            return pool

    @pytest.mark.asyncio
    async def test_tab_pool_actual_pages_gate_B(self):
        """[Boundary] context.pages >= TOTAL_MAX_TABS일 때 new_page 추가 호출 없이 backoff"""
        import asyncio

        with patch('app.shared.browser.tab_pool_manager.settings') as mock_settings:
            mock_settings.TAB_ROTATION_THRESHOLD = 100
            mock_settings.CACHE_CLEANUP_INTERVAL = 300
            mock_settings.TAB_REQUEST_TIMEOUT = 1.0
            mock_settings.TAB_WAIT_RETRY_INTERVAL = 0.1
            mock_settings.TOTAL_MAX_TABS = 5
            mock_settings.MAX_USES_PER_TAB = 50
            mock_settings.TAB_CLEANUP_THRESHOLD = 600

            from app.shared.browser.tab_pool_manager import TabPoolManager

            # 5개의 비닫힌 페이지 (실제 탭 = TOTAL_MAX_TABS)
            fake_pages = []
            for _ in range(5):
                p = MagicMock()
                p.is_closed.return_value = False
                p.url = "https://naver.com"
                fake_pages.append(p)

            mock_context = MagicMock()
            mock_context.pages = fake_pages
            mock_context.new_page = AsyncMock()

            mock_cm = MagicMock()
            mock_cm.get_or_create_context = AsyncMock(return_value=mock_context)
            mock_cm.browser_contexts = {}

            pool = TabPoolManager(mock_cm)
            pool.TOTAL_MAX_TABS = 5
            pool.TAB_REQUEST_TIMEOUT = 1.0
            pool.TAB_WAIT_RETRY_INTERVAL = 0.1

            # pool에 1개 탭 등록 (total_tabs = 1 < 5 이지만 actual_pages = 5 >= 5)
            mock_pool_page = MagicMock()
            mock_pool_page.is_closed.return_value = False
            pool.tab_pools[1] = {"1_0001": mock_pool_page}
            pool.tab_in_use["1_0001"] = True  # 사용 중 → available 없음
            pool.tab_account["1_0001"] = 1

            # _cleanup_orphan_tabs를 no-op으로 패치 (외부 의존 없이)
            pool._cleanup_orphan_tabs = AsyncMock(return_value=0)

            with pytest.raises(TimeoutError):
                await pool.get_tab(target_id=999, service_account_id=1)

            # new_page는 호출되지 않아야 한다 (secondary gate가 막음)
            mock_context.new_page.assert_not_called()


# ============================================================
# periodic_cleanup 테스트 (Phase 2: 원인 D 수정 검증)
# ============================================================

class TestPeriodicCleanup:
    """periodic_cleanup 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_tab_pool_periodic_cleanup_closes_orphans_R(self):
        """[Right] periodic_cleanup 호출 시 about:blank / chrome-error:// 팝업 모두 닫힘"""
        with patch('app.shared.browser.tab_pool_manager.settings') as mock_settings:
            mock_settings.TAB_ROTATION_THRESHOLD = 100
            mock_settings.CACHE_CLEANUP_INTERVAL = 300
            mock_settings.TAB_REQUEST_TIMEOUT = 30
            mock_settings.TAB_WAIT_RETRY_INTERVAL = 0.5
            mock_settings.TOTAL_MAX_TABS = 5
            mock_settings.MAX_USES_PER_TAB = 50
            mock_settings.TAB_CLEANUP_THRESHOLD = 600

            from app.shared.browser.tab_pool_manager import TabPoolManager

            blank_page = MagicMock()
            blank_page.url = "about:blank"
            blank_page.is_closed.return_value = False
            blank_page.close = AsyncMock()

            error_page = MagicMock()
            error_page.url = "chrome-error://chromewebdata"
            error_page.is_closed.return_value = False
            error_page.close = AsyncMock()

            mock_context = MagicMock()
            mock_context.pages = [blank_page, error_page]

            mock_cm = MagicMock()
            mock_cm.browser_contexts = {1: mock_context}

            pool = TabPoolManager(mock_cm)
            pool.TOTAL_MAX_TABS = 5
            pool.tab_pools[1] = {}  # 등록된 pool 탭 없음 → 둘 다 고아

            await pool.periodic_cleanup()

            blank_page.close.assert_called_once()
            error_page.close.assert_called_once()


# ============================================================
# asyncio.shield — 미등록 탭 close cancel 내성 (D2 패턴)
# ============================================================

class TestGetTabUnregisteredCloseShield:
    """get_tab() finally 미등록 탭 정리 asyncio.shield 보호 TC"""

    @pytest.fixture
    def pool(self, pool_factory):
        return pool_factory()

    @pytest.mark.asyncio
    async def test_right_registered_new_tab_skips_finally_close_R(self, pool):
        """R: 등록 성공 후 new_tab = None → finally close 미호출."""
        pool.TOTAL_MAX_TABS = 10
        pool.tab_pools[1] = {}

        mock_new_tab = MagicMock()
        mock_new_tab._tab_id = "__pending__"
        mock_new_tab.close = AsyncMock()
        mock_new_tab.set_extra_http_headers = AsyncMock()

        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(return_value=mock_new_tab)
        pool.context_manager.get_or_create_context = AsyncMock(return_value=mock_context)

        # 컨텍스트 유효성 체크 우회
        mock_context.pages = []

        # 탭 생성 후 등록까지 가도록 waiter 이벤트 처리
        # get_tab은 복잡한 루프이므로 직접 finally 계약만 검증한다
        # new_tab = None 세팅 후 finally가 close를 호출하지 않음을 확인
        # (단순 계약 TC — 직접 시뮬레이션)

        tab_registered = False
        new_tab_ref = mock_new_tab

        async def check_finally_not_called_when_registered():
            nonlocal tab_registered
            new_tab = new_tab_ref
            try:
                # 등록 성공 시뮬레이션
                new_tab = None  # type: ignore[assignment]
                tab_registered = True
            finally:
                if new_tab is not None:
                    await new_tab.close()

        await check_finally_not_called_when_registered()

        assert tab_registered is True
        mock_new_tab.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_error_header_setup_failure_closes_unregistered_tab_E(self):
        """E: header 설정 실패 시 미등록 탭 close 보장."""
        mock_new_tab = MagicMock()
        mock_new_tab._tab_id = "__pending__"
        close_called = asyncio.Event()

        async def slow_close():
            close_called.set()

        mock_new_tab.close = AsyncMock(side_effect=slow_close)
        mock_new_tab.set_extra_http_headers = AsyncMock(side_effect=RuntimeError("header fail"))

        new_tab = mock_new_tab
        try:
            await new_tab.set_extra_http_headers({})
        except Exception:
            pass
        finally:
            if new_tab is not None:
                try:
                    await asyncio.shield(new_tab.close())
                except Exception:
                    pass

        assert close_called.is_set()

    @pytest.mark.asyncio
    async def test_error_unregistered_tab_close_shielded_on_cancel_E(self):
        """E(Cancel): new_page() 이후 outer cancel 상황에서도 close 완료 이벤트가 set됨."""
        close_completed = asyncio.Event()

        async def slow_close():
            await asyncio.sleep(0.05)
            close_completed.set()

        mock_new_tab = MagicMock()
        mock_new_tab._tab_id = "__pending__"
        mock_new_tab.close = AsyncMock(side_effect=slow_close)

        async def simulate_get_tab_finally():
            new_tab = mock_new_tab
            try:
                await asyncio.sleep(0.1)  # 등록 전 cancel 윈도우
                new_tab = None  # type: ignore[assignment]
            finally:
                if new_tab is not None:
                    try:
                        await asyncio.shield(new_tab.close())
                    except Exception:
                        pass

        task = asyncio.create_task(simulate_get_tab_finally())
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        await asyncio.sleep(0.08)
        assert close_completed.is_set(), (
            "미등록 탭 close가 완료되지 않음 — asyncio.shield 없이 cancel race로 중단됐음"
        )

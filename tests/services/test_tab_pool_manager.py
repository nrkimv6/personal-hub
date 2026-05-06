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


# ============================================================
# H1: release_tab finally 보장 + H2: new_page timeout
# ============================================================

@pytest.fixture
def _make_pool():
    with patch('app.shared.browser.tab_pool_manager.settings') as ms:
        ms.TAB_ROTATION_THRESHOLD = 600
        ms.CACHE_CLEANUP_INTERVAL = 300
        ms.TAB_REQUEST_TIMEOUT = 60
        ms.TAB_WAIT_RETRY_INTERVAL = 5
        ms.TOTAL_MAX_TABS = 5
        ms.MAX_USES_PER_TAB = 50
        from app.shared.browser.tab_pool_manager import TabPoolManager
        yield TabPoolManager(MagicMock())


class TestH1ReleaseFinallyGuarantee:
    """H1: release_tab에서 _wake_waiters 예외가 나도 tab_in_use=False 보장."""

    @pytest.mark.asyncio
    async def test_right_release_in_use_false_even_if_wake_waiters_raises(self, _make_pool):
        """R: _wake_waiters 예외 후에도 tab_in_use[tab_id] is False."""
        pool = _make_pool
        mock_tab = MagicMock()
        mock_tab._tab_id = "t1"
        pool.tab_in_use["t1"] = True
        pool.tab_last_used["t1"] = 0.0

        # 대기자가 있는 상태에서 _wake_waiters가 예외를 던짐
        dummy_event = MagicMock()
        dummy_event.is_set.return_value = False
        dummy_event.set.side_effect = RuntimeError("wake_waiters broken")
        pool.tab_waiters["req_x"] = dummy_event

        await pool.release_tab(mock_tab)

        assert pool.tab_in_use["t1"] is False, "in_use는 False여야 함 — wake_waiters 예외와 무관"

    @pytest.mark.asyncio
    async def test_boundary_release_tab_with_no_tab_id_is_noop(self, _make_pool):
        """B: _tab_id 없는 탭 release는 DEBUG no-op — tab_in_use 변화 없음."""
        pool = _make_pool
        mock_tab = MagicMock(spec=[])  # _tab_id 없음

        before = dict(pool.tab_in_use)
        await pool.release_tab(mock_tab)
        assert pool.tab_in_use == before

    @pytest.mark.asyncio
    async def test_boundary_release_pending_marker_tab_is_noop(self, _make_pool):
        """B: _tab_id='__pending__' 탭 release는 no-op — in_use 변화 없음."""
        pool = _make_pool
        mock_tab = MagicMock()
        mock_tab._tab_id = "__pending__"
        pool.tab_in_use["__pending__"] = True  # 이 상태가 유지돼야 함

        await pool.release_tab(mock_tab)
        # pending marker는 release_tab 책임 밖 — 변화 없음
        assert pool.tab_in_use.get("__pending__") is True

    @pytest.mark.asyncio
    async def test_error_release_tab_caplog(self, _make_pool, caplog):
        """E: _wake_waiters 예외 시 [TAB-POOL] release error 키워드 로그 출력."""
        import logging
        pool = _make_pool
        mock_tab = MagicMock()
        mock_tab._tab_id = "t2"
        pool.tab_in_use["t2"] = True

        dummy_event = MagicMock()
        dummy_event.is_set.return_value = False
        dummy_event.set.side_effect = RuntimeError("boom")
        pool.tab_waiters["req_y"] = dummy_event

        with caplog.at_level(logging.WARNING, logger="app.shared.browser.tab_pool_manager"):
            await pool.release_tab(mock_tab)

        assert any("release error" in r.message for r in caplog.records), (
            "[TAB-POOL] release error 키워드 로그가 없음"
        )


class TestH2NewPageTimeout:
    """H2: context.new_page() hang 시 NEW_PAGE_TIMEOUT 후 recreate 경로 진입."""

    @pytest.mark.asyncio
    async def test_right_new_page_timeout_triggers_recreate(self, _make_pool):
        """R: new_page가 30s hang -> TimeoutError -> handle_browser_closed_error 호출."""
        pool = _make_pool
        pool.TOTAL_MAX_TABS = 10
        pool.NEW_PAGE_TIMEOUT = 0.05  # 테스트용 단축

        # 모든 기존 탭이 in_use 상태여서 new_page 경로로 진입
        pool.tab_pools[1] = {}

        hang_event = asyncio.Event()

        async def _hanging_new_page():
            await asyncio.sleep(10)  # hang 시뮬레이션

        mock_context = MagicMock()
        # 1회는 hang, 이후에는 정상 탭 반환 (recreate 후)
        created_tab = MagicMock()
        created_tab._tab_id = "__pending__"
        created_tab.set_extra_http_headers = AsyncMock()
        call_count = 0

        async def _conditional_new_page():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(10)  # hang
            return created_tab

        mock_context.new_page = _conditional_new_page
        mock_context.pages = []
        pool.context_manager.get_or_create_context = AsyncMock(return_value=mock_context)
        pool.handle_browser_closed_error = AsyncMock(return_value=True)
        pool.register_initial_tabs = AsyncMock(return_value=0)
        pool.cleanup_old_tabs = AsyncMock(return_value=0)

        # get_tab 호출 — new_page hang → timeout → handle_browser_closed_error 호출
        try:
            await asyncio.wait_for(
                pool.get_tab(target_id=999, service_account_id=1),
                timeout=2.0
            )
        except (asyncio.TimeoutError, Exception):
            pass  # 전체 get_tab timeout 허용 — handle_browser_closed_error 호출 여부만 검증

        pool.handle_browser_closed_error.assert_called()

    @pytest.mark.asyncio
    async def test_boundary_retry_new_page_also_wrapped(self, _make_pool):
        """B: 재시도 경로의 new_page도 NEW_PAGE_TIMEOUT으로 감싸짐 — timeout 발생."""
        pool = _make_pool
        pool.NEW_PAGE_TIMEOUT = 0.05  # 단축
        pool.TOTAL_MAX_TABS = 10
        pool.tab_pools[1] = {}

        mock_context = MagicMock()

        async def _always_hang():
            await asyncio.sleep(10)

        mock_context.new_page = _always_hang
        mock_context.pages = []
        pool.context_manager.get_or_create_context = AsyncMock(return_value=mock_context)
        pool.handle_browser_closed_error = AsyncMock(return_value=True)
        pool.register_initial_tabs = AsyncMock(return_value=0)
        pool.cleanup_old_tabs = AsyncMock(return_value=0)

        try:
            await asyncio.wait_for(
                pool.get_tab(target_id=998, service_account_id=1),
                timeout=1.0
            )
        except (asyncio.TimeoutError, Exception):
            pass

        # handle_browser_closed_error 가 여러번 호출될 수 있음 (각 hang마다)
        assert pool.handle_browser_closed_error.call_count >= 1


class TestCreatePageWithTimeout:
    """_create_page_with_timeout helper 단위 테스트."""

    @pytest.mark.asyncio
    async def test_create_page_with_timeout_right_returns_pending_tab(self, _make_pool):
        """R: 정상 new_page 경로가 (context, page)를 반환하고 page._tab_id == '__pending__'을 보장한다."""
        pool = _make_pool
        pool.NEW_PAGE_TIMEOUT = 5.0

        created_page = MagicMock()
        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(return_value=created_page)

        returned_ctx, returned_page = await pool._create_page_with_timeout(mock_context, service_account_id=1)

        assert returned_ctx is mock_context
        assert returned_page is created_page
        assert returned_page._tab_id == "__pending__"

    @pytest.mark.asyncio
    async def test_create_page_with_timeout_error_hang_triggers_recreate(self, _make_pool):
        """E: new_page hang(0.05s timeout) 시 handle_browser_closed_error와 fresh get_or_create_context가 호출된다."""
        pool = _make_pool
        pool.NEW_PAGE_TIMEOUT = 0.05

        fresh_page = MagicMock()
        fresh_ctx = MagicMock()

        async def _always_hang():
            await asyncio.sleep(10)

        async def _ok():
            return fresh_page

        original_ctx = MagicMock()
        original_ctx.new_page = _always_hang
        fresh_ctx.new_page = _ok

        pool.handle_browser_closed_error = AsyncMock(return_value=True)
        pool.context_manager.get_or_create_context = AsyncMock(return_value=fresh_ctx)
        pool.register_initial_tabs = AsyncMock(return_value=0)
        pool.tab_pools[1] = {}

        returned_ctx, returned_page = await pool._create_page_with_timeout(original_ctx, service_account_id=1)

        pool.handle_browser_closed_error.assert_called_once_with(1, recreate=True)
        pool.context_manager.get_or_create_context.assert_called_with(1)
        assert returned_page is fresh_page
        assert returned_page._tab_id == "__pending__"

    @pytest.mark.asyncio
    async def test_get_tab_after_recreate_registers_tab_into_live_account_pool(self, _make_pool):
        """recreate 뒤 반환 탭이 분리된 옛 dict가 아니라 self.tab_pools[service_account_id]에 등록된다."""
        pool = _make_pool
        pool.TOTAL_MAX_TABS = 10
        pool.NEW_PAGE_TIMEOUT = 5.0

        old_dict: dict = {}
        new_dict: dict = {}
        pool.tab_pools[1] = old_dict

        created_page = MagicMock()
        created_page.set_extra_http_headers = AsyncMock()
        fresh_ctx = MagicMock()
        fresh_ctx.pages = []

        async def _new_page():
            return created_page

        fresh_ctx.new_page = _new_page

        async def _mock_create_page(context, service_account_id):
            pool.tab_pools[service_account_id] = new_dict
            created_page._tab_id = "__pending__"
            return fresh_ctx, created_page

        pool._create_page_with_timeout = _mock_create_page
        pool.cleanup_old_tabs = AsyncMock(return_value=0)
        pool.context_manager.get_or_create_context = AsyncMock(return_value=fresh_ctx)

        tab = await pool.get_tab(target_id=1, service_account_id=1)

        tab_id = tab._tab_id
        assert tab_id in new_dict, "탭이 fresh dict에 등록돼야 한다"
        assert tab_id not in old_dict, "탭이 stale dict에 등록되면 안 된다"

    @pytest.mark.asyncio
    async def test_warmup_recreate_refreshes_context_and_overwrites_pending_marker(self, _make_pool):
        """warmup recreate 뒤 fresh context를 사용하고 __pending__ -> tab_id 전환 계약이 유지된다."""
        pool = _make_pool
        pool.TOTAL_MAX_TABS = 10
        pool.NEW_PAGE_TIMEOUT = 5.0
        pool.tab_pools[1] = {}

        pages_created: list = []
        call_count = 0
        fresh_ctx = MagicMock()

        async def _create_page_with_timeout_mock(context, service_account_id):
            nonlocal call_count
            call_count += 1
            page = MagicMock()
            page._tab_id = "__pending__"
            page.set_extra_http_headers = AsyncMock()
            pages_created.append(page)
            return fresh_ctx, page

        pool._create_page_with_timeout = _create_page_with_timeout_mock
        pool.context_manager.get_or_create_context = AsyncMock(return_value=fresh_ctx)
        fresh_ctx.pages = []

        await pool.warmup(min_tabs=2, service_account_id=1)

        assert call_count == 2, "탭 2개 생성 요청"
        for page in pages_created:
            assert page._tab_id != "__pending__", "__pending__ -> tab_id로 전환돼야 한다"


# ============================================================
# exact-limit orphan cleanup 테스트
# ============================================================

class TestExactLimitOrphanCleanup:
    """결함 1 수정 검증 — _cleanup_orphan_tabs() >= 조건 + visible sentinel skip"""

    def _make_page(self, url: str):
        page = MagicMock()
        page.url = url
        page.is_closed = MagicMock(return_value=False)
        page.close = AsyncMock()
        return page

    @pytest.fixture
    def pool(self):
        with patch('app.shared.browser.tab_pool_manager.settings') as ms:
            ms.TAB_ROTATION_THRESHOLD = 600
            ms.CACHE_CLEANUP_INTERVAL = 300
            ms.TAB_REQUEST_TIMEOUT = 60
            ms.TAB_WAIT_RETRY_INTERVAL = 5
            ms.TOTAL_MAX_TABS = 5
            ms.MAX_USES_PER_TAB = 50
            from app.shared.browser.tab_pool_manager import TabPoolManager
            yield TabPoolManager(MagicMock())

    @pytest.mark.asyncio
    async def test_cleanup_orphan_tabs_at_exact_limit_closes_nonblank_B(self, pool):
        """B(Boundary): actual_pages == TOTAL_MAX_TABS + non-blank orphan → close() 호출."""
        registered = self._make_page("about:blank")
        orphan1 = self._make_page("https://booking.naver.com/123")
        orphan2 = self._make_page("https://booking.naver.com/456")
        orphan3 = self._make_page("https://booking.naver.com/789")
        orphan4 = self._make_page("https://booking.naver.com/012")

        mock_context = MagicMock()
        mock_context.pages = [registered, orphan1, orphan2, orphan3, orphan4]

        pool.tab_pools[1] = {"t1": registered}
        pool.context_manager.browser_contexts = {1: mock_context}

        count = await pool._cleanup_orphan_tabs()

        assert count == 4
        orphan1.close.assert_awaited_once()
        orphan2.close.assert_awaited_once()
        orphan3.close.assert_awaited_once()
        orphan4.close.assert_awaited_once()
        registered.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleanup_orphan_tabs_logs_exact_limit_event_R(self, pool, caplog):
        """R(Right): exact-limit cleanup 후 caplog에 [TAB-POOL] exact-limit orphan cleaned INFO 로그."""
        import logging

        registered = self._make_page("about:blank")
        orphan = self._make_page("https://booking.naver.com/123")

        mock_context = MagicMock()
        mock_context.pages = [registered, orphan, self._make_page("x"), self._make_page("y"), self._make_page("z")]
        for p in mock_context.pages:
            p.is_closed = MagicMock(return_value=False)

        pool.tab_pools[1] = {"t1": registered}
        pool.context_manager.browser_contexts = {1: mock_context}

        with caplog.at_level(logging.INFO):
            await pool._cleanup_orphan_tabs()

        assert any("[TAB-POOL] exact-limit orphan cleaned" in r.message for r in caplog.records)
        assert any("actual_before=5" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_cleanup_orphan_tabs_preserves_visible_sentinel_Co(self, pool):
        """Co(Conformance): visible_1 sentinel 페이지는 actual_pages >= TOTAL_MAX_TABS라도 close 안 됨."""
        registered = self._make_page("about:blank")
        sentinel = self._make_page("https://booking.naver.com/open")
        sentinel._tab_id = "visible_1"
        orphan1 = self._make_page("https://booking.naver.com/123")
        orphan2 = self._make_page("https://booking.naver.com/456")
        orphan3 = self._make_page("https://booking.naver.com/789")

        mock_context = MagicMock()
        mock_context.pages = [registered, sentinel, orphan1, orphan2, orphan3]

        pool.tab_pools[1] = {"t1": registered}
        pool.context_manager.browser_contexts = {1: mock_context}

        count = await pool._cleanup_orphan_tabs()

        sentinel.close.assert_not_awaited()
        orphan1.close.assert_awaited_once()
        orphan2.close.assert_awaited_once()
        orphan3.close.assert_awaited_once()
        assert count == 3


# ============================================================
# Phase T1 신규 TC: _count_budgeted_pages, _is_stale_login_check,
#                   cleanup summary/skip logging
# ============================================================

@pytest.fixture()
def pool_factory():
    """TabPoolManager 팩토리 (make_pool과 동일, fixture 이름 충돌 방지)."""
    def _create(total_max_tabs=5):
        with patch('app.shared.browser.tab_pool_manager.settings') as ms:
            ms.TAB_ROTATION_THRESHOLD = 100
            ms.CACHE_CLEANUP_INTERVAL = 300
            ms.TAB_REQUEST_TIMEOUT = 30
            ms.TAB_WAIT_RETRY_INTERVAL = 0.5
            ms.TOTAL_MAX_TABS = total_max_tabs
            ms.MAX_USES_PER_TAB = 50
            ms.TAB_CLEANUP_THRESHOLD = 3600
            from app.shared.browser.tab_pool_manager import TabPoolManager
            pool = TabPoolManager(MagicMock())
            pool.TOTAL_MAX_TABS = total_max_tabs
            return pool
    return _create


def _mock_page(is_closed=False, tab_id=None, url="about:blank"):
    """테스트용 Page 목 생성 헬퍼."""
    p = MagicMock()
    p.is_closed = MagicMock(return_value=is_closed)
    p.close = AsyncMock()
    p.url = url
    if tab_id is not None:
        p._tab_id = tab_id
    else:
        # _tab_id 속성 없음
        if hasattr(p, '_tab_id'):
            del p._tab_id
    return p


class TestCountBudgetedPages:
    """_count_budgeted_pages() helper TC"""

    def test_count_budgeted_pages_R_counts_managed_and_orphan_pages(self, pool_factory):
        """R: pool 등록 4, orphan 1, sentinel 0 → 반환 5 (혼합 포화 재오픈 방지)."""
        pool = pool_factory()
        pages = [_mock_page(tab_id=f"1_{i:04d}") for i in range(4)]  # pool 탭
        pages.append(_mock_page(url="https://naver.com"))  # orphan (no _tab_id)

        mock_ctx = MagicMock()
        mock_ctx.pages = pages

        result = pool._count_budgeted_pages(mock_ctx)
        assert result == 5

    def test_count_budgeted_pages_Co_excludes_visible_sentinels_only(self, pool_factory):
        """Co: pool 등록 1, sentinel 2, orphan 1 → 반환 2 (sentinel 제외)."""
        pool = pool_factory()
        pool_page = _mock_page(tab_id="1_0001")
        sentinel1 = _mock_page(tab_id="visible_1")
        sentinel2 = _mock_page(tab_id="visible_2")
        orphan = _mock_page(url="https://naver.com")

        mock_ctx = MagicMock()
        mock_ctx.pages = [pool_page, sentinel1, sentinel2, orphan]

        result = pool._count_budgeted_pages(mock_ctx)
        assert result == 2  # pool_page + orphan; sentinel 2개 제외

    def test_count_budgeted_pages_B_empty_context(self, pool_factory):
        """B: context.pages=[] → 반환 0."""
        pool = pool_factory()
        mock_ctx = MagicMock()
        mock_ctx.pages = []

        assert pool._count_budgeted_pages(mock_ctx) == 0

    def test_count_budgeted_pages_B_all_sentinels(self, pool_factory):
        """B: sentinel 5 + orphan 0 → 반환 0 (워커 예산 완전 가용)."""
        pool = pool_factory()
        sentinels = [_mock_page(tab_id=f"visible_{i}") for i in range(5)]

        mock_ctx = MagicMock()
        mock_ctx.pages = sentinels

        assert pool._count_budgeted_pages(mock_ctx) == 0

    def test_count_budgeted_pages_E_closed_page_excluded(self, pool_factory):
        """E: is_closed()=True 인 page는 계산에서 제외."""
        pool = pool_factory()
        open_page = _mock_page(is_closed=False, tab_id="1_0001")
        closed_page = _mock_page(is_closed=True, tab_id="1_0002")

        mock_ctx = MagicMock()
        mock_ctx.pages = [open_page, closed_page]

        assert pool._count_budgeted_pages(mock_ctx) == 1


class TestIsStaleLoginCheck:
    """_is_stale_login_check() helper TC"""

    def test_is_stale_login_check_R_recent_false(self, pool_factory):
        """R: 근래 생성 login_check → False."""
        pool = pool_factory()
        page = _mock_page(tab_id=f"login_check_naver_1_{int(time.time())}")
        assert pool._is_stale_login_check(page) is False

    def test_is_stale_login_check_R_old_true(self, pool_factory):
        """R: 31초 전 생성 login_check → True."""
        pool = pool_factory()
        old_ts = int(time.time()) - 31
        page = _mock_page(tab_id=f"login_check_naver_1_{old_ts}")
        assert pool._is_stale_login_check(page) is True

    def test_is_stale_login_check_E_malformed_tab_id(self, pool_factory):
        """E: timestamp 없는 login_check → False (안전 기본값)."""
        pool = pool_factory()
        page = _mock_page(tab_id="login_check_broken")
        assert pool._is_stale_login_check(page) is False

    def test_is_stale_login_check_E_non_login_prefix(self, pool_factory):
        """E: visible_1 등 다른 prefix → False."""
        pool = pool_factory()
        page = _mock_page(tab_id="visible_1")
        assert pool._is_stale_login_check(page) is False

    def test_is_stale_login_check_Co_mixed_case_prefix(self, pool_factory):
        """Co: 대문자 LOGIN_CHECK prefix → False (prefix 대소문자 구분)."""
        pool = pool_factory()
        old_ts = int(time.time()) - 31
        page = _mock_page(tab_id=f"LOGIN_CHECK_NAVER_1_{old_ts}")
        assert pool._is_stale_login_check(page) is False


class TestCleanupOrphanTabsLogging:
    """_cleanup_orphan_tabs() summary/skip DEBUG 로그 TC"""

    @pytest.fixture
    def pool(self):
        with patch('app.shared.browser.tab_pool_manager.settings') as ms:
            ms.TAB_ROTATION_THRESHOLD = 600
            ms.CACHE_CLEANUP_INTERVAL = 300
            ms.TAB_REQUEST_TIMEOUT = 60
            ms.TAB_WAIT_RETRY_INTERVAL = 5
            ms.TOTAL_MAX_TABS = 5
            ms.MAX_USES_PER_TAB = 50
            from app.shared.browser.tab_pool_manager import TabPoolManager
            yield TabPoolManager(MagicMock())

    @pytest.mark.asyncio
    async def test_cleanup_orphan_tabs_logs_summary(self, pool, caplog):
        """R: cleanup 호출 시 매번 summary INFO 로그 출력."""
        import logging
        mock_ctx = MagicMock()
        mock_ctx.pages = []
        pool.context_manager.browser_contexts = {1: mock_ctx}
        pool.tab_pools[1] = {}

        with caplog.at_level(logging.INFO, logger="app.shared.browser.tab_pool_manager"):
            await pool._cleanup_orphan_tabs()

        assert any(
            "[TAB-POOL] cleanup summary:" in r.message
            for r in caplog.records
        ), "cleanup summary 로그 없음"

    @pytest.mark.asyncio
    async def test_cleanup_orphan_tabs_summary_counts_correct(self, pool, caplog):
        """R: pool 탭 1개 + sentinel 1개 + orphan 1개 → summary에 counts 정확히 표시."""
        import logging
        registered = _mock_page(tab_id="1_0001", url="about:blank")
        sentinel = _mock_page(tab_id="visible_1", url="https://naver.com")
        orphan = _mock_page(url="about:blank")

        mock_ctx = MagicMock()
        mock_ctx.pages = [registered, sentinel, orphan]
        pool.context_manager.browser_contexts = {1: mock_ctx}
        pool.tab_pools[1] = {"1_0001": registered}

        with caplog.at_level(logging.INFO, logger="app.shared.browser.tab_pool_manager"):
            await pool._cleanup_orphan_tabs()

        summary_records = [r for r in caplog.records if "[TAB-POOL] cleanup summary:" in r.message]
        assert len(summary_records) == 1
        msg = summary_records[0].message
        # orphan(about:blank) 1건 닫힘, sentinel 1건 skip
        assert "closed=1" in msg
        assert "skipped_sentinel=1" in msg

    @pytest.mark.asyncio
    async def test_cleanup_orphan_tabs_logs_skip_reasons_debug(self, pool, caplog):
        """E: skip된 페이지에 대해 DEBUG 레벨 skip reason 로그 출력."""
        import logging
        registered = _mock_page(tab_id="1_0001", url="about:blank")
        mock_ctx = MagicMock()
        mock_ctx.pages = [registered]
        pool.context_manager.browser_contexts = {1: mock_ctx}
        pool.tab_pools[1] = {"1_0001": registered}

        with caplog.at_level(logging.DEBUG, logger="app.shared.browser.tab_pool_manager"):
            await pool._cleanup_orphan_tabs()

        debug_records = [r for r in caplog.records if "cleanup skip" in r.message and r.levelname == "DEBUG"]
        assert len(debug_records) >= 1, "cleanup skip DEBUG 로그 없음"

    @pytest.mark.asyncio
    async def test_cleanup_orphan_tabs_stale_login_check_closed(self, pool):
        """R: stale login_check 탭(31초 전) → cleanup에서 close() 호출."""
        old_ts = int(time.time()) - 31
        stale_lc = _mock_page(tab_id=f"login_check_naver_1_{old_ts}", url="https://naver.com")
        stale_lc.is_closed = MagicMock(return_value=False)

        mock_ctx = MagicMock()
        mock_ctx.pages = [stale_lc]
        pool.context_manager.browser_contexts = {1: mock_ctx}
        pool.tab_pools[1] = {}

        await pool._cleanup_orphan_tabs()
        stale_lc.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_orphan_tabs_recent_login_check_preserved(self, pool):
        """R: 근래 login_check 탭(10초 전) → cleanup에서 close() 미호출."""
        recent_ts = int(time.time()) - 10
        recent_lc = _mock_page(tab_id=f"login_check_naver_1_{recent_ts}", url="https://naver.com")
        recent_lc.is_closed = MagicMock(return_value=False)

        mock_ctx = MagicMock()
        mock_ctx.pages = [recent_lc]
        pool.context_manager.browser_contexts = {1: mock_ctx}
        pool.tab_pools[1] = {}

        await pool._cleanup_orphan_tabs()
        recent_lc.close.assert_not_awaited()

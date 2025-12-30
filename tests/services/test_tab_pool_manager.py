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

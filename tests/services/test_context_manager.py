"""
ContextManager 테스트

RIGHT-BICEP 원칙 적용:
- Right: 결과가 올바른가?
- Boundary: 경계값 테스트
- Inverse: 역관계 검증
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트

테스트 대상:
- ContextManager: 계정별 브라우저 컨텍스트 관리
  - 컨텍스트 생성/조회/종료
  - 프록시 설정
  - 자동화 감지 방지
  - 창 위치 이동
  - 스크린샷
"""

import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# 1. ContextManager 초기화 테스트
# ============================================================

class TestContextManagerInit:
    """ContextManager 초기화 테스트"""

    def test_right_init_default(self):
        """
        [Right] 기본 초기화
        """
        from app.shared.browser.context_manager import ContextManager

        manager = ContextManager()

        assert manager.browser_contexts == {}
        assert manager.browser_context is None
        assert manager.playwright_instance is None
        assert manager._proxy_manager is None

    def test_right_init_with_proxy_manager(self):
        """
        [Right] 프록시 매니저와 함께 초기화
        """
        from app.shared.browser.context_manager import ContextManager

        mock_proxy = MagicMock()
        manager = ContextManager(proxy_manager=mock_proxy)

        assert manager._proxy_manager is mock_proxy


# ============================================================
# 2. 프록시 설정 테스트
# ============================================================

class TestProxyConfiguration:
    """프록시 설정 테스트"""

    @pytest.fixture
    def manager(self):
        from app.shared.browser.context_manager import ContextManager
        return ContextManager()

    def test_right_set_proxy_manager(self, manager):
        """
        [Right] 프록시 매니저 설정
        """
        mock_proxy = MagicMock()
        manager.set_proxy_manager(mock_proxy)

        assert manager._proxy_manager is mock_proxy

    def test_right_set_proxy_manager_none(self, manager):
        """
        [Right] 프록시 매니저 해제
        """
        mock_proxy = MagicMock()
        manager._proxy_manager = mock_proxy

        manager.set_proxy_manager(None)

        assert manager._proxy_manager is None

    def test_right_get_proxy_config_available(self, manager):
        """
        [Right] 프록시 설정 조회 (사용 가능)
        """
        mock_proxy = MagicMock()
        mock_proxy.is_available = True
        mock_proxy.get_playwright_proxy.return_value = {
            "server": "http://proxy.example.com:8080"
        }
        manager._proxy_manager = mock_proxy

        result = manager._get_proxy_config()

        assert result is not None
        assert result["server"] == "http://proxy.example.com:8080"

    def test_right_get_proxy_config_unavailable(self, manager):
        """
        [Right] 프록시 설정 조회 (사용 불가)
        """
        mock_proxy = MagicMock()
        mock_proxy.is_available = False
        manager._proxy_manager = mock_proxy

        result = manager._get_proxy_config()

        assert result is None

    def test_right_get_proxy_config_no_manager(self, manager):
        """
        [Right] 프록시 매니저 없을 때
        """
        result = manager._get_proxy_config()

        assert result is None


# ============================================================
# 3. 컨텍스트 Lock 테스트
# ============================================================

class TestContextLock:
    """컨텍스트 Lock 테스트"""

    @pytest.fixture
    def manager(self):
        from app.shared.browser.context_manager import ContextManager
        return ContextManager()

    @pytest.mark.asyncio
    async def test_right_get_or_create_lock(self, manager):
        """
        [Right] Lock 생성 및 조회
        """
        lock1 = await manager._get_context_lock(1)
        lock2 = await manager._get_context_lock(1)

        assert lock1 is lock2
        assert isinstance(lock1, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_right_different_locks_for_different_accounts(self, manager):
        """
        [Right] 다른 계정은 다른 Lock
        """
        lock1 = await manager._get_context_lock(1)
        lock2 = await manager._get_context_lock(2)

        assert lock1 is not lock2


# ============================================================
# 4. 컨텍스트 종료 테스트
# ============================================================

class TestCloseContext:
    """컨텍스트 종료 테스트"""

    @pytest.fixture
    def manager(self):
        from app.shared.browser.context_manager import ContextManager
        return ContextManager()

    @pytest.mark.asyncio
    async def test_right_close_context_success(self, manager):
        """
        [Right] 컨텍스트 종료 성공
        """
        mock_context = MagicMock()
        mock_context.close = AsyncMock()
        manager.browser_contexts[1] = mock_context

        await manager.close_context(1)

        mock_context.close.assert_called_once()
        assert 1 not in manager.browser_contexts

    @pytest.mark.asyncio
    async def test_right_close_context_not_exists(self, manager):
        """
        [Right] 존재하지 않는 컨텍스트 종료 (예외 없음)
        """
        # 예외 없이 완료
        await manager.close_context(999)

    @pytest.mark.asyncio
    async def test_error_close_context_exception(self, manager):
        """
        [Error] 종료 중 예외 발생해도 딕셔너리에서 제거 시도
        """
        mock_context = MagicMock()
        mock_context.close = AsyncMock(side_effect=Exception("종료 실패"))
        manager.browser_contexts[1] = mock_context

        # 예외 없이 완료 (에러 로깅만)
        await manager.close_context(1)


# ============================================================
# 5. 모든 컨텍스트 종료 테스트
# ============================================================

class TestCloseAllContexts:
    """모든 컨텍스트 종료 테스트"""

    @pytest.fixture
    def manager(self):
        from app.shared.browser.context_manager import ContextManager
        return ContextManager()

    @pytest.mark.asyncio
    async def test_right_close_all_contexts(self, manager):
        """
        [Right] 모든 컨텍스트 종료
        """
        mock_ctx1 = MagicMock()
        mock_ctx1.close = AsyncMock()
        mock_ctx2 = MagicMock()
        mock_ctx2.close = AsyncMock()

        manager.browser_contexts = {1: mock_ctx1, 2: mock_ctx2}

        mock_playwright = MagicMock()
        mock_playwright.stop = AsyncMock()
        manager.playwright_instance = mock_playwright

        await manager.close_all_contexts()

        mock_ctx1.close.assert_called_once()
        mock_ctx2.close.assert_called_once()
        mock_playwright.stop.assert_called_once()
        assert manager.playwright_instance is None

    @pytest.mark.asyncio
    async def test_right_close_all_no_playwright(self, manager):
        """
        [Right] Playwright 인스턴스 없어도 정상 종료
        """
        mock_ctx = MagicMock()
        mock_ctx.close = AsyncMock()
        manager.browser_contexts = {1: mock_ctx}
        manager.playwright_instance = None

        await manager.close_all_contexts()

        mock_ctx.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_close_all_playwright_error(self, manager):
        """
        [Error] Playwright 종료 실패해도 예외 없음
        """
        mock_playwright = MagicMock()
        mock_playwright.stop = AsyncMock(side_effect=Exception("종료 실패"))
        manager.playwright_instance = mock_playwright

        # 예외 없이 완료
        await manager.close_all_contexts()


# ============================================================
# 6. 자동화 감지 방지 테스트
# ============================================================

class TestAntiDetection:
    """자동화 감지 방지 테스트"""

    @pytest.fixture
    def manager(self):
        from app.shared.browser.context_manager import ContextManager
        return ContextManager()

    def test_right_get_anti_detection_script(self, manager):
        """
        [Right] 자동화 감지 방지 스크립트 반환
        """
        script = manager._get_anti_detection_script()

        # 주요 스크립트 요소 확인
        assert "navigator.webdriver" in script
        assert "window.chrome" in script
        assert "navigator.plugins" in script
        assert "navigator.languages" in script

    @pytest.mark.asyncio
    async def test_right_bypass_automation_detection(self, manager):
        """
        [Right] 자동화 감지 방지 스크립트 주입
        """
        mock_context = MagicMock()
        mock_context.add_init_script = AsyncMock()

        await manager._bypass_automation_detection(mock_context)

        mock_context.add_init_script.assert_called_once()
        # 스크립트가 전달되었는지 확인
        args = mock_context.add_init_script.call_args[0]
        assert "webdriver" in args[0]


# ============================================================
# 7. 창 위치 이동 테스트
# ============================================================

class TestMoveWindow:
    """창 위치 이동 테스트"""

    @pytest.fixture
    def manager(self):
        from app.shared.browser.context_manager import ContextManager
        return ContextManager()

    @pytest.mark.asyncio
    async def test_right_move_window_to_center(self, manager):
        """
        [Right] 창을 중앙으로 이동
        """
        mock_page = MagicMock()
        mock_cdp = MagicMock()
        mock_cdp.send = AsyncMock(side_effect=[
            {"windowId": 123},  # getWindowForTarget
            None,               # setWindowBounds
        ])
        mock_page.context = MagicMock()
        mock_page.context.new_cdp_session = AsyncMock(return_value=mock_cdp)

        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        manager.browser_context = mock_context

        result = await manager.move_window_to_center()

        assert result is True
        # setWindowBounds 호출 확인
        calls = mock_cdp.send.call_args_list
        assert calls[1][0][0] == "Browser.setWindowBounds"

    @pytest.mark.asyncio
    async def test_right_move_window_to_corner(self, manager):
        """
        [Right] 창을 구석으로 이동
        """
        mock_page = MagicMock()
        mock_cdp = MagicMock()
        mock_cdp.send = AsyncMock(side_effect=[
            {"windowId": 123},
            None,
        ])
        mock_page.context = MagicMock()
        mock_page.context.new_cdp_session = AsyncMock(return_value=mock_cdp)

        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        manager.browser_context = mock_context

        result = await manager.move_window_to_corner()

        assert result is True

    @pytest.mark.asyncio
    async def test_boundary_move_window_no_context(self, manager):
        """
        [Boundary] 브라우저 컨텍스트 없을 때
        """
        manager.browser_context = None

        result_center = await manager.move_window_to_center()
        result_corner = await manager.move_window_to_corner()

        assert result_center is False
        assert result_corner is False

    @pytest.mark.asyncio
    async def test_boundary_move_window_no_pages(self, manager):
        """
        [Boundary] 열린 페이지가 없을 때
        """
        mock_context = MagicMock()
        mock_context.pages = []
        manager.browser_context = mock_context

        result = await manager.move_window_to_center()

        assert result is False

    @pytest.mark.asyncio
    async def test_error_move_window_cdp_error(self, manager):
        """
        [Error] CDP 에러 발생 시 False 반환
        """
        mock_page = MagicMock()
        mock_page.context = MagicMock()
        mock_page.context.new_cdp_session = AsyncMock(
            side_effect=Exception("CDP 에러")
        )

        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        manager.browser_context = mock_context

        result = await manager.move_window_to_center()

        assert result is False


# ============================================================
# 8. 스크린샷 테스트
# ============================================================

class TestScreenshot:
    """스크린샷 테스트"""

    @pytest.fixture
    def manager(self):
        from app.shared.browser.context_manager import ContextManager
        return ContextManager()

    @pytest.mark.asyncio
    async def test_right_take_screenshot(self, manager):
        """
        [Right] 스크린샷 저장
        """
        import tempfile
        import os

        mock_page = MagicMock()
        mock_page.screenshot = AsyncMock()

        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        manager.browser_context = mock_context

        # 임시 디렉토리 사용
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch('app.shared.browser.context_manager.settings') as mock_settings:
                mock_settings.BASE_DIR = temp_dir
                result = await manager.take_screenshot("test")

        assert result is not None
        assert "test" in result
        mock_page.screenshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_right_take_screenshots_all_pages(self, manager):
        """
        [Right] 모든 페이지 스크린샷
        """
        import tempfile

        mock_page1 = MagicMock()
        mock_page1.screenshot = AsyncMock()
        mock_page2 = MagicMock()
        mock_page2.screenshot = AsyncMock()

        mock_context = MagicMock()
        mock_context.pages = [mock_page1, mock_page2]
        manager.browser_context = mock_context

        # 임시 디렉토리 사용
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch('app.shared.browser.context_manager.settings') as mock_settings:
                mock_settings.BASE_DIR = temp_dir
                result = await manager.take_screenshots_all_pages("test")

        assert len(result) == 2
        mock_page1.screenshot.assert_called_once()
        mock_page2.screenshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_boundary_screenshot_no_context(self, manager):
        """
        [Boundary] 브라우저 컨텍스트 없을 때
        """
        manager.browser_context = None

        result = await manager.take_screenshot("test")

        assert result is None

    @pytest.mark.asyncio
    async def test_boundary_screenshot_no_pages(self, manager):
        """
        [Boundary] 열린 페이지가 없을 때
        """
        mock_context = MagicMock()
        mock_context.pages = []
        manager.browser_context = mock_context

        result = await manager.take_screenshot("test")

        assert result is None

    @pytest.mark.asyncio
    async def test_error_screenshot_page_error(self, manager):
        """
        [Error] 페이지 스크린샷 실패해도 다른 페이지는 계속
        """
        import tempfile

        mock_page1 = MagicMock()
        mock_page1.screenshot = AsyncMock(side_effect=Exception("스크린샷 실패"))
        mock_page2 = MagicMock()
        mock_page2.screenshot = AsyncMock()

        mock_context = MagicMock()
        mock_context.pages = [mock_page1, mock_page2]
        manager.browser_context = mock_context

        # 임시 디렉토리 사용
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch('app.shared.browser.context_manager.settings') as mock_settings:
                mock_settings.BASE_DIR = temp_dir
                result = await manager.take_screenshots_all_pages("test")

        # 두 번째 페이지는 성공
        assert len(result) == 1


# ============================================================
# 9. get_or_create_context 테스트
# ============================================================

class TestGetOrCreateContext:
    """get_or_create_context 테스트"""

    @pytest.fixture
    def manager(self):
        from app.shared.browser.context_manager import ContextManager
        return ContextManager()

    @pytest.mark.asyncio
    async def test_right_get_existing_context(self, manager):
        """
        [Right] 기존 컨텍스트 반환
        """
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_page.url = "https://example.com"
        mock_context.pages = [mock_page]

        manager.browser_contexts[1] = mock_context

        result = await manager.get_or_create_context(service_account_id=1)

        assert result is mock_context

    @pytest.mark.asyncio
    async def test_right_create_new_context(self, manager):
        """
        [Right] 새 컨텍스트 생성
        """
        mock_context = MagicMock()

        manager._create_browser_context = AsyncMock(return_value=mock_context)

        with patch('app.core.database.SessionLocal') as mock_session_local:
            mock_db = MagicMock()
            mock_session_local.return_value = mock_db

            # default profile 조회 모킹
            with patch('app.shared.browser_profile.browser_profile_service.get_default_profile') as mock_get_default:
                mock_get_default.return_value = None

                result = await manager.get_or_create_context(service_account_id=1)

        assert result is mock_context
        assert 1 in manager.browser_contexts

    @pytest.mark.asyncio
    async def test_right_recreate_invalid_context(self, manager):
        """
        [Right] 유효하지 않은 컨텍스트는 재생성
        """
        # 유효하지 않은 컨텍스트 (pages 접근 시 예외)
        invalid_context = MagicMock()
        invalid_context.pages = PropertyMock(side_effect=Exception("Closed"))

        manager.browser_contexts[1] = invalid_context

        new_context = MagicMock()
        manager._create_browser_context = AsyncMock(return_value=new_context)

        result = await manager.get_or_create_context(service_account_id=1)

        assert result is new_context

    @pytest.mark.asyncio
    async def test_right_first_context_sets_browser_context(self, manager):
        """
        [Right] 첫 번째 컨텍스트는 browser_context에도 저장
        """
        mock_context = MagicMock()
        manager._create_browser_context = AsyncMock(return_value=mock_context)

        assert manager.browser_context is None

        with patch('app.core.database.SessionLocal') as mock_session_local:
            mock_db = MagicMock()
            mock_session_local.return_value = mock_db

            with patch('app.shared.browser_profile.browser_profile_service.get_default_profile') as mock_get_default:
                mock_get_default.return_value = None

                await manager.get_or_create_context(service_account_id=1)

        assert manager.browser_context is mock_context


# ============================================================
# 10. 컨텍스트 유효성 검사 테스트
# ============================================================

class TestContextValidation:
    """컨텍스트 유효성 검사 테스트"""

    @pytest.fixture
    def manager(self):
        from app.shared.browser.context_manager import ContextManager
        return ContextManager()

    @pytest.mark.asyncio
    async def test_right_valid_context_with_pages(self, manager):
        """
        [Right] 페이지가 있는 유효한 컨텍스트
        """
        mock_page = MagicMock()
        mock_page.url = "https://example.com"

        mock_context = MagicMock()
        mock_context.pages = [mock_page]

        manager.browser_contexts[1] = mock_context

        result = await manager.get_or_create_context(service_account_id=1)

        assert result is mock_context

    @pytest.mark.asyncio
    async def test_right_valid_context_no_pages_connected_browser(self, manager):
        """
        [Right] 페이지 없지만 브라우저 연결됨
        """
        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = True

        mock_context = MagicMock()
        mock_context.pages = []
        mock_context.browser = mock_browser

        manager.browser_contexts[1] = mock_context

        result = await manager.get_or_create_context(service_account_id=1)

        assert result is mock_context

    @pytest.mark.asyncio
    async def test_error_context_page_access_failure(self, manager):
        """
        [Error] 페이지 접근 실패 시 재생성
        """
        mock_page = MagicMock()
        # url 접근 시 예외
        type(mock_page).url = PropertyMock(side_effect=Exception("Page closed"))

        mock_context = MagicMock()
        mock_context.pages = [mock_page]

        manager.browser_contexts[1] = mock_context

        new_context = MagicMock()
        manager._create_browser_context = AsyncMock(return_value=new_context)

        result = await manager.get_or_create_context(service_account_id=1)

        assert result is new_context
        assert 1 not in manager.browser_contexts or manager.browser_contexts[1] is new_context


# ============================================================
# 11. 동시성 테스트
# ============================================================

class TestConcurrency:
    """동시성 테스트"""

    @pytest.fixture
    def manager(self):
        from app.shared.browser.context_manager import ContextManager
        return ContextManager()

    @pytest.mark.asyncio
    async def test_right_concurrent_context_creation(self, manager):
        """
        [Right] 동시 컨텍스트 생성 시 Lock으로 보호
        """
        create_count = 0

        async def mock_create(service_account_id):
            nonlocal create_count
            create_count += 1
            await asyncio.sleep(0.1)  # 생성 시간 시뮬레이션
            return MagicMock()

        manager._create_browser_context = mock_create

        with patch('app.core.database.SessionLocal') as mock_session_local:
            mock_db = MagicMock()
            mock_session_local.return_value = mock_db

            with patch('app.shared.browser_profile.browser_profile_service.get_default_profile') as mock_get_default:
                mock_get_default.return_value = None

                # 동시에 같은 계정으로 3번 요청
                tasks = [
                    manager.get_or_create_context(service_account_id=1),
                    manager.get_or_create_context(service_account_id=1),
                    manager.get_or_create_context(service_account_id=1),
                ]

                results = await asyncio.gather(*tasks)

        # Lock으로 인해 생성은 1번만 되어야 함
        assert create_count == 1
        # 모두 같은 컨텍스트 반환
        assert results[0] is results[1] is results[2]


# ============================================================
# 팝업 핸들러 테스트 (Phase 1: 원인 B 수정 검증)
# ============================================================

class TestPopupHandlerRegistration:
    """팝업 차단 핸들러 등록 테스트"""

    def _make_manager(self):
        from app.shared.browser.context_manager import ContextManager
        return ContextManager()

    def test_tab_pool_popup_handler_registered_R(self):
        """[Right] context.on('page') 첫 호출 시 1회만 등록, 재호출 시 중복 등록 없음"""
        manager = self._make_manager()
        mock_context = MagicMock()
        mock_context.pages = []

        manager._register_popup_handler(service_account_id=1, context=mock_context)
        manager._register_popup_handler(service_account_id=1, context=mock_context)

        assert mock_context.on.call_count == 1
        assert 1 in manager._popup_handler_registered

    def test_tab_pool_popup_handler_skips_registered_tab_Co(self):
        """[Conformance] pool 등록 탭(_tab_id 속성 있음)은 close() 호출 안 함"""
        manager = self._make_manager()
        mock_context = MagicMock()
        mock_context.pages = []

        captured_handler = None

        def _capture_on(event, handler):
            nonlocal captured_handler
            captured_handler = handler

        mock_context.on.side_effect = _capture_on
        manager._register_popup_handler(service_account_id=1, context=mock_context)

        assert captured_handler is not None

        mock_page = MagicMock()
        mock_page._tab_id = "1_1234"

        captured_handler(mock_page)

        mock_page.close.assert_not_called()

    def test_tab_pool_popup_handler_closes_orphan_R(self):
        """[Right] _tab_id 없는 팝업 페이지에 대해 close task가 생성됨"""
        import asyncio
        manager = self._make_manager()
        mock_context = MagicMock()
        mock_context.pages = []

        captured_handler = None

        def _capture_on(event, handler):
            nonlocal captured_handler
            captured_handler = handler

        mock_context.on.side_effect = _capture_on
        manager._register_popup_handler(service_account_id=1, context=mock_context)

        assert captured_handler is not None

        close_called = []
        mock_page = MagicMock(spec=[])
        mock_page.close = AsyncMock(side_effect=lambda: close_called.append(True))

        async def run():
            captured_handler(mock_page)
            await asyncio.sleep(0.05)

        asyncio.get_event_loop().run_until_complete(run())
        assert len(close_called) == 1

    def test_tab_pool_popup_handler_cleans_preexisting_orphan_E(self):
        """[Existence] 핸들러 등록 이전의 about:blank 고아 탭을 즉시 close task 생성"""
        import asyncio
        manager = self._make_manager()

        close_called = []
        mock_page = MagicMock(spec=[])
        mock_page.url = "about:blank"
        mock_page.close = AsyncMock(side_effect=lambda: close_called.append(True))

        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_context.on = MagicMock()

        async def run():
            manager._register_popup_handler(service_account_id=2, context=mock_context)
            await asyncio.sleep(0.05)

        asyncio.get_event_loop().run_until_complete(run())
        assert len(close_called) == 1

    def test_mixed_orphan_and_managed_tab_only_orphan_closed_E(self):
        """[Existence] _tab_id 있는 managed tab과 about:blank orphan이 섞여 있을 때 orphan만 닫힌다 (Phase T1 item 8)."""
        import asyncio
        manager = self._make_manager()

        closed = []

        orphan = MagicMock(spec=[])
        orphan.url = "about:blank"
        orphan.is_closed = MagicMock(return_value=False)
        orphan.close = AsyncMock(side_effect=lambda: closed.append("orphan"))
        # _tab_id 없음 — direct context.new_page() 경로

        managed = MagicMock(spec=[])
        managed.url = "about:blank"
        managed.is_closed = MagicMock(return_value=False)
        managed.close = AsyncMock(side_effect=lambda: closed.append("managed"))
        managed._tab_id = "__pending__"  # tab_pool_manager 설정 마커

        mock_context = MagicMock()
        mock_context.pages = [orphan, managed]
        mock_context.on = MagicMock()

        async def run():
            manager._register_popup_handler(service_account_id=3, context=mock_context)
            await asyncio.sleep(0.1)

        asyncio.get_event_loop().run_until_complete(run())
        assert "orphan" in closed
        assert "managed" not in closed

    def test_popup_handler_discard_on_close_context(self):
        """close_context 호출 시 _popup_handler_registered에서 제거됨"""
        import asyncio
        manager = self._make_manager()
        manager._popup_handler_registered.add(5)
        manager.browser_contexts[5] = AsyncMock()

        asyncio.get_event_loop().run_until_complete(manager.close_context(5))
        assert 5 not in manager._popup_handler_registered


# ============================================================
# _create_browser_context_visible popup handler 등록 테스트 (결함 2A)
# ============================================================

class TestCreateBrowserContextVisiblePopupHandler:
    """_create_browser_context_visible()가 재사용/신규 양쪽에서 popup handler를 등록하는지 검증."""

    @pytest.fixture
    def manager(self):
        from app.shared.browser.context_manager import ContextManager
        return ContextManager()

    @pytest.mark.asyncio
    async def test_create_browser_context_visible_registers_popup_handler_on_reuse_E(self, manager):
        """E(Existence): 재사용 경로에서 _register_popup_handler 1회 호출 검증."""
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_page.url = "https://naver.com"
        mock_context.pages = [mock_page]
        manager.browser_contexts[1] = mock_context

        manager._register_popup_handler = MagicMock()

        result = await manager._create_browser_context_visible(1)

        assert result is mock_context
        manager._register_popup_handler.assert_called_once_with(1, mock_context)

    @pytest.mark.asyncio
    async def test_create_browser_context_visible_registers_popup_handler_on_new_E(self, manager):
        """E(Existence): 신규 생성 경로에서 _register_popup_handler 1회 호출 검증."""
        mock_context = MagicMock()
        mock_account = MagicMock()
        mock_account.profile.profile_path = "/tmp/nonexistent_profile_test_abc"
        mock_account.profile.profile_dir = "test_dir"
        mock_db = MagicMock()

        manager._register_popup_handler = MagicMock()

        with (
            patch("app.core.database.SessionLocal", return_value=mock_db),
            patch("app.shared.service_account.service_account_service") as mock_svc,
        ):
            mock_svc.get_by_id.return_value = mock_account
            mock_svc.update_last_used = MagicMock()

            mock_playwright = MagicMock()
            mock_playwright.chromium.launch_persistent_context = AsyncMock(return_value=mock_context)
            manager.playwright_instance = mock_playwright

            with patch.object(manager, "_bypass_automation_detection", new=AsyncMock()):
                result = await manager._create_browser_context_visible(1)

        assert result is mock_context
        manager._register_popup_handler.assert_called_once_with(1, mock_context)


# ============================================================
# 실행
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

"""
SessionManager 로그인 체크 메서드의 cancel-safe close 테스트 (RIGHT-BICEP)

대상:
- check_naver_login_status(): finally page.close() asyncio.shield 보호
- check_instagram_login_status(): 동일 패턴
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ============================================================
# check_naver_login_status
# ============================================================

class TestCheckNaverLoginStatusCloseShield:

    @pytest.fixture
    def mock_page(self, mock_playwright_page):
        return mock_playwright_page

    @pytest.fixture
    def manager(self, session_manager_with_mock_context):
        return session_manager_with_mock_context

    @pytest.mark.asyncio
    async def test_normal_path_closes_page_R(self, mock_page, manager):
        """R: 정상 경로 — page.close() 정확히 1회 호출."""

        mock_account = MagicMock()
        mock_account.profile.name = "테스트계정"
        mock_db = MagicMock()

        with (
            patch("app.shared.browser.session_manager.SessionLocal", return_value=mock_db),
            patch(
                "app.shared.service_account.service_account_service.service_account_service"
            ) as mock_svc,
        ):
            mock_svc.get_by_id.return_value = mock_account
            mock_svc.update_login_status = MagicMock()
            await manager.check_naver_login_status(service_account_id=1)

        mock_page.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_account_skips_page_B(self, mock_page, manager):
        """B: 계정 없음 — context/page 생성 없이 조기 반환."""
        mock_db = MagicMock()

        with (
            patch("app.shared.browser.session_manager.SessionLocal", return_value=mock_db),
            patch(
                "app.shared.service_account.service_account_service.service_account_service"
            ) as mock_svc,
        ):
            mock_svc.get_by_id.return_value = None
            result = await manager.check_naver_login_status(service_account_id=99)

        assert result["success"] is False
        mock_page.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_close_shielded_on_cancel_E(self, mock_page, manager):
        """E(Cancel): 외부 cancel 후에도 page.close() 완료 이벤트가 set됨."""
        close_completed = asyncio.Event()

        async def slow_close():
            await asyncio.sleep(0.05)
            close_completed.set()

        mock_page.close = AsyncMock(side_effect=slow_close)

        mock_account = MagicMock()
        mock_account.profile.name = "테스트계정"
        mock_db = MagicMock()

        with (
            patch("app.shared.browser.session_manager.SessionLocal", return_value=mock_db),
            patch(
                "app.shared.service_account.service_account_service.service_account_service"
            ) as mock_svc,
        ):
            mock_svc.get_by_id.return_value = mock_account
            mock_svc.update_login_status = MagicMock()

            task = asyncio.create_task(manager.check_naver_login_status(service_account_id=1))
            await asyncio.sleep(0.01)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        await asyncio.sleep(0.08)
        assert close_completed.is_set(), (
            "page.close()가 완료되지 않음 — asyncio.shield 없이 cancel race로 중단됐음"
        )


# ============================================================
# check_instagram_login_status
# ============================================================

class TestCheckInstagramLoginStatusCloseShield:

    @pytest.fixture
    def mock_page(self, mock_playwright_page):
        return mock_playwright_page

    @pytest.fixture
    def manager(self, session_manager_with_mock_context):
        return session_manager_with_mock_context

    @pytest.mark.asyncio
    async def test_normal_path_closes_page_R(self, mock_page, manager):
        """R: 정상 경로 — page.close() 정확히 1회 호출."""
        mock_page.query_selector = AsyncMock(return_value=MagicMock())

        mock_account = MagicMock()
        mock_account.profile.name = "테스트계정"
        mock_db = MagicMock()

        with (
            patch("app.shared.browser.session_manager.SessionLocal", return_value=mock_db),
            patch(
                "app.shared.service_account.service_account_service.service_account_service"
            ) as mock_svc,
        ):
            mock_svc.get_by_id.return_value = mock_account
            mock_svc.update_login_status = MagicMock()
            await manager.check_instagram_login_status(service_account_id=1)

        mock_page.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_account_skips_page_B(self, mock_page, manager):
        """B: 계정 없음 — page 생성 없이 조기 반환."""
        mock_db = MagicMock()

        with (
            patch("app.shared.browser.session_manager.SessionLocal", return_value=mock_db),
            patch(
                "app.shared.service_account.service_account_service.service_account_service"
            ) as mock_svc,
        ):
            mock_svc.get_by_id.return_value = None
            result = await manager.check_instagram_login_status(service_account_id=99)

        assert result["success"] is False
        mock_page.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_close_shielded_on_cancel_E(self, mock_page, manager):
        """E(Cancel): 외부 cancel 후에도 page.close() 완료 이벤트가 set됨."""
        close_completed = asyncio.Event()

        async def slow_close():
            await asyncio.sleep(0.05)
            close_completed.set()

        mock_page.close = AsyncMock(side_effect=slow_close)

        mock_account = MagicMock()
        mock_account.profile.name = "테스트계정"
        mock_db = MagicMock()

        with (
            patch("app.shared.browser.session_manager.SessionLocal", return_value=mock_db),
            patch(
                "app.shared.service_account.service_account_service.service_account_service"
            ) as mock_svc,
        ):
            mock_svc.get_by_id.return_value = mock_account
            mock_svc.update_login_status = MagicMock()

            task = asyncio.create_task(manager.check_instagram_login_status(service_account_id=1))
            await asyncio.sleep(0.01)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        await asyncio.sleep(0.08)
        assert close_completed.is_set(), (
            "page.close()가 완료되지 않음 — asyncio.shield 없이 cancel race로 중단됐음"
        )



# ============================================================
# open_browser_for_account visible sentinel 테스트 (결함 2B)
# ============================================================

class TestOpenBrowserForAccountSentinel:
    """open_browser_for_account()가 visible sentinel을 올바르게 설정하고 재사용하는지 검증."""

    def _make_account(self):
        import unittest.mock as um
        account = um.MagicMock()
        account.profile.name = "테스트계정"
        account.profile.profile_path = "/tmp/nonexistent_test_profile"
        return account

    @pytest.mark.asyncio
    async def test_open_browser_for_account_sets_visible_sentinel_R(self):
        """R(Right): 첫 호출 시 page._tab_id == 'visible_1' 설정, 재호출 시 new_page 미호출."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.shared.browser.session_manager import SessionManager

        new_page_call_count = 0
        sentinel_page = MagicMock()
        sentinel_page.goto = AsyncMock()
        sentinel_page.url = "about:blank"
        sentinel_page.is_closed = MagicMock(return_value=False)

        mock_context = MagicMock()

        async def _new_page():
            nonlocal new_page_call_count
            new_page_call_count += 1
            mock_context.pages = [sentinel_page]
            return sentinel_page

        mock_context.new_page = _new_page
        mock_context.pages = []

        mock_cm = MagicMock()
        mock_cm.browser_contexts = {}
        mock_cm._create_browser_context_visible = AsyncMock(return_value=mock_context)

        manager = SessionManager(mock_cm)
        mock_db = MagicMock()

        with (
            patch("app.shared.browser.session_manager.SessionLocal", return_value=mock_db),
            patch("app.shared.service_account.service_account_service.service_account_service") as mock_svc,
            patch("pathlib.Path.exists", return_value=False),
        ):
            mock_svc.get_by_id.return_value = self._make_account()
            await manager.open_browser_for_account(service_account_id=1, url=None)

        assert new_page_call_count == 1
        assert getattr(sentinel_page, '_tab_id', None) == "visible_1"

        # 두 번째 호출: sentinel 탭이 context.pages에 있으므로 new_page 미호출
        with (
            patch("app.shared.browser.session_manager.SessionLocal", return_value=mock_db),
            patch("app.shared.service_account.service_account_service.service_account_service") as mock_svc,
            patch("pathlib.Path.exists", return_value=False),
        ):
            mock_svc.get_by_id.return_value = self._make_account()
            await manager.open_browser_for_account(service_account_id=1, url=None)

        assert new_page_call_count == 1, "두 번째 호출에서 new_page가 추가 호출되면 안 됨"

    @pytest.mark.asyncio
    async def test_open_browser_for_account_reuse_path_sets_sentinel_Co(self):
        """Co(Conformance): 기존 컨텍스트 재사용 경로(pages[0])에서도 sentinel 없으면 부여됨."""
        import types
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.shared.browser.session_manager import SessionManager

        # SimpleNamespace 사용: _tab_id 없음 → hasattr 정확히 False 반환
        cdp = AsyncMock()
        cdp.send = AsyncMock(side_effect=Exception("cdp_not_needed"))
        page_context = MagicMock()
        page_context.new_cdp_session = AsyncMock(return_value=cdp)

        existing_page = types.SimpleNamespace(
            url="https://booking.naver.com/123",
            goto=AsyncMock(),
            bring_to_front=AsyncMock(),
            context=page_context,
        )

        mock_context = MagicMock()
        mock_context.pages = [existing_page]
        mock_context.browser = MagicMock()
        mock_context.browser.is_connected = MagicMock(return_value=True)

        mock_cm = MagicMock()
        mock_cm.browser_contexts = {1: mock_context}

        manager = SessionManager(mock_cm)
        mock_db = MagicMock()

        with (
            patch("app.shared.browser.session_manager.SessionLocal", return_value=mock_db),
            patch("app.shared.service_account.service_account_service.service_account_service") as mock_svc,
            patch("pathlib.Path.exists", return_value=False),
        ):
            mock_svc.get_by_id.return_value = self._make_account()
            await manager.open_browser_for_account(service_account_id=1, url=None)

        assert getattr(existing_page, '_tab_id', None) == "visible_1", (
            "재사용 경로에서도 sentinel이 부여되어야 함"
        )

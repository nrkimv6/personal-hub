"""
SessionManager 로그인 체크 메서드의 cancel-safe close 테스트 (RIGHT-BICEP)

대상:
- check_naver_login_status(): finally page.close() asyncio.shield 보호
- check_instagram_login_status(): 동일 패턴
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_page():
    page = MagicMock()
    page.goto = AsyncMock()
    page.content = AsyncMock(return_value="<html>로그인</html>")
    page.query_selector = AsyncMock(return_value=None)
    page.close = AsyncMock()
    page.evaluate = AsyncMock(return_value=None)
    return page


def _make_session_manager(mock_page):
    from app.shared.browser.session_manager import SessionManager

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_context_manager = MagicMock()
    mock_context_manager._create_browser_context_visible = AsyncMock(return_value=mock_context)

    return SessionManager(mock_context_manager)


# ============================================================
# check_naver_login_status
# ============================================================

class TestCheckNaverLoginStatusCloseShield:

    @pytest.mark.asyncio
    async def test_normal_path_closes_page_R(self):
        """R: 정상 경로 — page.close() 정확히 1회 호출."""
        mock_page = _make_mock_page()
        manager = _make_session_manager(mock_page)

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
    async def test_missing_account_skips_page_B(self):
        """B: 계정 없음 — context/page 생성 없이 조기 반환."""
        mock_page = _make_mock_page()
        manager = _make_session_manager(mock_page)
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
    async def test_close_shielded_on_cancel_E(self):
        """E(Cancel): 외부 cancel 후에도 page.close() 완료 이벤트가 set됨."""
        close_completed = asyncio.Event()

        async def slow_close():
            await asyncio.sleep(0.05)
            close_completed.set()

        mock_page = _make_mock_page()
        mock_page.close = AsyncMock(side_effect=slow_close)
        manager = _make_session_manager(mock_page)

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

    @pytest.mark.asyncio
    async def test_normal_path_closes_page_R(self):
        """R: 정상 경로 — page.close() 정확히 1회 호출."""
        mock_page = _make_mock_page()
        mock_page.query_selector = AsyncMock(return_value=MagicMock())
        manager = _make_session_manager(mock_page)

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
    async def test_missing_account_skips_page_B(self):
        """B: 계정 없음 — page 생성 없이 조기 반환."""
        mock_page = _make_mock_page()
        manager = _make_session_manager(mock_page)
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
    async def test_close_shielded_on_cancel_E(self):
        """E(Cancel): 외부 cancel 후에도 page.close() 완료 이벤트가 set됨."""
        close_completed = asyncio.Event()

        async def slow_close():
            await asyncio.sleep(0.05)
            close_completed.set()

        mock_page = _make_mock_page()
        mock_page.close = AsyncMock(side_effect=slow_close)
        manager = _make_session_manager(mock_page)

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

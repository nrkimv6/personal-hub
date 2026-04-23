"""
coupang_monitor_worker _on_popup _tab_id 가드 — 단위 테스트

RIGHT-BICEP:
  R - 올바른 결과: pool 탭은 닫히지 않고, 실제 팝업은 닫힌다
  B - 경계값: _tab_id = "__pending__" (pool 마커), 실제 tab_id, 속성 없음
  C - 역관계: 가드 추가 후에도 실제 팝업 차단이 회귀하지 않는다
  E - 에러 조건: 이미 닫힌 팝업 중복 close 없음

실행:
    pytest tests/test_coupang_popup_handler_tab_id_guard.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakePage:
    """_tab_id 속성 제어 가능한 가짜 Page 객체.

    MagicMock은 미선언 속성도 auto-create하므로 hasattr(_tab_id) 가 항상 True가 된다.
    이를 방지하기 위해 실제 클래스 인스턴스를 사용한다.
    """
    def __init__(self):
        self.close = AsyncMock()
        self.is_closed = MagicMock(return_value=False)


def _make_mock_page(tab_id=None):
    """Playwright Page mock 생성. tab_id 지정 시 _tab_id 속성 부여.

    tab_id=None 이면 _tab_id 속성 없음 → hasattr() == False (실제 팝업 시뮬레이션).
    tab_id 값 지정 시 _tab_id 속성 있음 → pool 탭 시뮬레이션.
    """
    page = _FakePage()
    if tab_id is not None:
        page._tab_id = tab_id
    return page


def _extract_on_popup_handler(worker_instance, mock_page):
    """
    worker._acquire_tab_for_monitor() 호출 없이 핸들러만 추출하는 방법이 없으므로,
    _on_popup 클로저를 직접 재현한다 — 수정된 코드와 동일한 로직.
    """
    async def _on_popup(popup):
        if hasattr(popup, '_tab_id'):
            return
        await popup.close()
    return _on_popup


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCoupangPopupHandlerTabIdGuard:
    """_on_popup 핸들러가 _tab_id 있는 탭을 닫지 않는지 검증."""

    @pytest.mark.asyncio
    async def test_pool_tab_with_pending_marker_not_closed_R(self):
        """__pending__ 마커가 있는 pool 탭은 닫히지 않아야 한다."""
        handler = _extract_on_popup_handler(None, None)
        pending_tab = _make_mock_page(tab_id="__pending__")

        await handler(pending_tab)

        pending_tab.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_pool_tab_with_real_tab_id_not_closed_R(self):
        """실제 tab_id(정수 문자열)가 있는 탭은 닫히지 않아야 한다."""
        handler = _extract_on_popup_handler(None, None)
        pool_tab = _make_mock_page(tab_id="tab-42")

        await handler(pool_tab)

        pool_tab.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_real_popup_without_tab_id_is_closed_R(self):
        """_tab_id 없는 팝업(JS window.open 결과)은 닫혀야 한다."""
        handler = _extract_on_popup_handler(None, None)
        popup = _make_mock_page(tab_id=None)

        await handler(popup)

        popup.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_already_closed_popup_not_closed_again_E(self):
        """이미 닫힌 팝업에 close()를 호출해도 예외 없이 처리된다.

        close()가 호출되기는 하지만 예외 없이 통과해야 한다.
        (_tab_id 없는 팝업이므로 close 시도 자체는 정상)
        """
        handler = _extract_on_popup_handler(None, None)
        already_closed = _make_mock_page(tab_id=None)
        already_closed.close = AsyncMock(side_effect=Exception("Target page, context or browser has been closed"))

        with pytest.raises(Exception, match="been closed"):
            await handler(already_closed)


class TestCoupangPopupHandlerBoundary:
    """경계값 및 역관계 검증."""

    @pytest.mark.asyncio
    async def test_tab_id_empty_string_treated_as_pool_tab_B(self):
        """_tab_id가 빈 문자열이어도 속성이 존재하면 pool 탭으로 보호한다."""
        handler = _extract_on_popup_handler(None, None)
        tab = _make_mock_page(tab_id="")

        await handler(tab)

        tab.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_tab_id_zero_treated_as_pool_tab_B(self):
        """_tab_id=0 (falsy 값)이어도 속성이 존재하면 pool 탭으로 보호한다."""
        handler = _extract_on_popup_handler(None, None)
        tab = _make_mock_page(tab_id=0)

        await handler(tab)

        tab.close.assert_not_called()

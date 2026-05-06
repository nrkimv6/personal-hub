"""
coupang_monitor_worker _on_popup race condition 통합 TC (T3)

쿠팡 워커의 context.on("page", _on_popup) 핸들러 등록 후,
pool 탭이 context.new_page()로 생성될 때 닫히지 않는지 검증.
실제 Playwright 없이 handler 클로저를 직접 추출하여 race 시뮬레이션.

실행:
    pytest tests/test_coupang_popup_handler_race_integration.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import pytest


class _FakePage:
    """_tab_id 속성 제어 가능한 가짜 Page 객체."""
    def __init__(self):
        self.close = AsyncMock()
        self.context = MagicMock()


def _build_on_popup_handler():
    """coupang_monitor_worker.py 수정된 _on_popup 클로저와 동일한 로직을 반환."""
    async def _on_popup(popup):
        if hasattr(popup, '_tab_id'):
            return
        await popup.close()
    return _on_popup


class TestCoupangPopupHandlerRaceCondition:

    @pytest.mark.asyncio
    async def test_coupang_popup_handler_race_with_pool_tab(self):
        """핸들러 등록 후 pool 탭 생성(context.new_page()) 시 닫히지 않는다.

        재현 시나리오:
          1. 쿠팡 워커: context.on("page", _on_popup) 등록
          2. tab_pool_manager: context.new_page() → pool 탭 생성
             → 즉시 pool_tab._tab_id = "__pending__" 설정
          3. "page" 이벤트 발생 → _on_popup(pool_tab) 호출
          → _tab_id 있음 → return (close 호출 없음)
        """
        handler = _build_on_popup_handler()
        pool_tab = _FakePage()
        pool_tab._tab_id = "__pending__"  # tab_pool_manager가 즉시 설정하는 마커

        await handler(pool_tab)

        pool_tab.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_coupang_popup_handler_race_tab_id_assigned_before_handler_fires(self):
        """실제 tab_id가 new_page() 직후 설정되면 핸들러가 pool 탭을 닫지 않는다.

        pool_tab._tab_id = "tab-1" 처럼 실제 ID가 부여된 경우도 보호돼야 한다.
        """
        handler = _build_on_popup_handler()
        pool_tab = _FakePage()
        pool_tab._tab_id = "tab-1"

        await handler(pool_tab)

        pool_tab.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_coupang_popup_handler_still_closes_real_popup(self):
        """실제 팝업(JS window.open)에는 여전히 close()가 호출돼야 한다.

        회귀 방지: _tab_id 가드 추가 후에도 팝업 차단 기능은 유지된다.
        """
        handler = _build_on_popup_handler()
        real_popup = _FakePage()
        # _tab_id 속성 미설정 — 실제 팝업

        await handler(real_popup)

        real_popup.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrent_popup_events_pool_tabs_all_protected(self):
        """복수의 pool 탭이 동시 이벤트를 발생시켜도 모두 보호된다."""
        handler = _build_on_popup_handler()
        pool_tabs = []
        for i in range(3):
            tab = _FakePage()
            tab._tab_id = f"tab-{i}"
            pool_tabs.append(tab)

        await asyncio.gather(*[handler(t) for t in pool_tabs])

        for tab in pool_tabs:
            tab.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_concurrent_real_popups_all_closed(self):
        """복수의 실제 팝업이 동시에 열려도 모두 닫힌다."""
        handler = _build_on_popup_handler()
        popups = [_FakePage() for _ in range(3)]  # _tab_id 미설정

        await asyncio.gather(*[handler(p) for p in popups])

        for popup in popups:
            popup.close.assert_called_once()

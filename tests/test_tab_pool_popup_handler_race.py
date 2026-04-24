"""
_on_popup 핸들러와 new_page() 사이 race condition 수정 검증

버그: context.on("page", _on_popup)이 context.new_page()도 트리거.
     _on_popup이 동기적으로 실행될 때 _tab_id 없음 → create_task(page.close()) 예약.
     이후 _tab_id를 설정해도 이미 close task가 예약되어 탭이 닫힘.

수정: 이중 방어
     1) _close_if_still_orphan: sleep(0) 후 _tab_id 재확인
     2) new_page() 직후 _tab_id = "__pending__" 동기 설정
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.shared.browser.context_manager import ContextManager


def _make_mock_context():
    context = MagicMock()
    page_handlers = []

    def capture_handler(event, handler):
        if event == "page":
            page_handlers.append(handler)

    context.on.side_effect = capture_handler
    context.pages = []
    context._page_handlers = page_handlers
    return context


class _FakePage:
    """MagicMock 대신 사용하는 경량 Page stub.

    MagicMock은 hasattr(mock, 'any_attr')이 항상 True를 반환하므로
    _tab_id 부재 테스트가 불가능하다.
    """

    def __init__(self, tab_id=None, closed=False):
        self.url = "about:blank"
        self._closed = closed
        self.close = AsyncMock()
        if tab_id is not None:
            self._tab_id = tab_id

    def is_closed(self):
        return self._closed


class TestPopupHandlerRace:
    """_on_popup 핸들러 race condition 수정 검증 (T1 단위 TC)"""

    @pytest.mark.asyncio
    async def test_new_page_with_pending_marker_not_closed_R(self):
        """__pending__ 마커 있는 탭은 핸들러가 닫지 않음 (RIGHT: 정상 경로)"""
        cm = ContextManager()
        mock_ctx = _make_mock_context()
        cm._register_popup_handler(1, mock_ctx)
        handler = mock_ctx._page_handlers[0]

        page = _FakePage(tab_id="__pending__")
        handler(page)
        await asyncio.sleep(0.1)

        page.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_real_orphan_without_tab_id_is_closed_R(self):
        """_tab_id 없는 팝업/고아 탭은 닫힘 — 팝업 차단 기능 유지 (RIGHT)"""
        cm = ContextManager()
        mock_ctx = _make_mock_context()
        cm._register_popup_handler(1, mock_ctx)
        handler = mock_ctx._page_handlers[0]

        page = _FakePage(tab_id=None)
        handler(page)
        await asyncio.sleep(0.1)

        page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_tab_id_set_before_sleep_prevents_close_B(self):
        """sleep(0) 이전에 _tab_id 설정 시 닫히지 않음 (B: 경계값)"""
        cm = ContextManager()
        mock_ctx = _make_mock_context()
        cm._register_popup_handler(1, mock_ctx)
        handler = mock_ctx._page_handlers[0]

        page = _FakePage(tab_id=None)
        handler(page)
        # 핸들러 호출 직후 동기로 _tab_id 설정 (실제 get_tab 패턴과 동일)
        page._tab_id = "1_5678"
        await asyncio.sleep(0.1)

        page.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_closed_page_not_closed_again_E(self):
        """이미 닫힌 탭은 추가 close 호출 없음 (E: 오류 경로)"""
        cm = ContextManager()
        mock_ctx = _make_mock_context()
        cm._register_popup_handler(1, mock_ctx)
        handler = mock_ctx._page_handlers[0]

        page = _FakePage(tab_id=None, closed=True)
        handler(page)
        await asyncio.sleep(0.1)

        page.close.assert_not_called()

    def test_handler_registered_only_once_B(self):
        """같은 계정에 핸들러 중복 등록 방지 (B: 경계값)"""
        cm = ContextManager()
        mock_ctx = _make_mock_context()

        cm._register_popup_handler(1, mock_ctx)
        cm._register_popup_handler(1, mock_ctx)

        page_event_calls = [c for c in mock_ctx.on.call_args_list if c[0][0] == "page"]
        assert len(page_event_calls) == 1


class TestPopupHandlerRaceReproduction:
    """race condition 실제 재현 및 수정 검증 (T3: 재현/통합 TC)"""

    @pytest.mark.asyncio
    async def test_race_condition_fixed_with_pending_marker(self):
        """
        버그 재현 시나리오:
        1. new_page() 완료 → page 이벤트 → _on_popup 동기 실행
        2. _tab_id 없음 → create_task(_close_if_still_orphan) 예약
        3. new_page() 반환 → 즉시 _tab_id = "__pending__" 동기 설정
        4. sleep(0) 이후 _close_if_still_orphan 재확인 → _tab_id 있음 → 닫지 않음
        """
        cm = ContextManager()
        mock_ctx = _make_mock_context()
        cm._register_popup_handler(1, mock_ctx)
        handler = mock_ctx._page_handlers[0]

        page = _FakePage(tab_id=None)

        # Step 1: page 이벤트 트리거 (new_page() 완료 시 동기 호출)
        handler(page)

        # Step 2: new_page() 반환 후 즉시 pending 마커 동기 설정
        page._tab_id = "__pending__"

        # Step 3: 첫 번째 await 지점 (실제: set_extra_http_headers)
        await asyncio.sleep(0)

        # Step 4: _close_if_still_orphan의 sleep(0) 후 재확인 완료 대기
        await asyncio.sleep(0.05)

        # 탭이 닫히지 않아야 함
        page.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_regression_real_popup_still_closed(self):
        """수정 후에도 실제 팝업(JS window.open)은 여전히 닫힘 — 회귀 없음"""
        cm = ContextManager()
        mock_ctx = _make_mock_context()
        cm._register_popup_handler(1, mock_ctx)
        handler = mock_ctx._page_handlers[0]

        # 실제 팝업: pool에 등록되지 않아 _tab_id 없음
        page = _FakePage(tab_id=None)

        handler(page)
        # _tab_id 설정 없이 대기
        await asyncio.sleep(0.1)

        page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrent_new_page_calls_no_closed_tabs(self):
        """다수 new_page() 동시 호출 시 모두 닫히지 않음 (P: 성능/병렬 경계)"""
        cm = ContextManager()
        mock_ctx = _make_mock_context()
        cm._register_popup_handler(1, mock_ctx)
        handler = mock_ctx._page_handlers[0]

        pages = [_FakePage(tab_id=None) for _ in range(5)]

        # 모두 핸들러 호출 후 즉시 pending 마커 설정 (실제 동시 new_page 패턴)
        for page in pages:
            handler(page)
            page._tab_id = "__pending__"

        await asyncio.sleep(0.1)

        for page in pages:
            page.close.assert_not_called()


class TestDirectVsManagedPagePopupGuard:
    """direct page(_tab_id 없음) vs managed page(__pending__) 혼합 시나리오 (Phase T1 item 8)."""

    @pytest.mark.asyncio
    async def test_direct_page_without_tab_id_is_closed_and_pending_page_survives_R(self):
        """R(Right): direct page(tab_id 없음)는 닫히고 __pending__ managed page는 살아남는다."""
        cm = ContextManager()
        mock_ctx = _make_mock_context()
        cm._register_popup_handler(1, mock_ctx)
        handler = mock_ctx._page_handlers[0]

        direct_page = _FakePage(tab_id=None)    # direct context.new_page() — 탭 풀 우회
        managed_page = _FakePage(tab_id="__pending__")  # tab_pool_manager가 설정한 pending 마커

        handler(direct_page)
        handler(managed_page)

        await asyncio.sleep(0.1)

        direct_page.close.assert_called_once()
        managed_page.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_mixed_pages_only_orphan_closed_in_same_event_loop_turn_R(self):
        """R(Right): 같은 event-loop turn에 고아와 managed 탭이 혼재해도 orphan만 닫힌다."""
        cm = ContextManager()
        mock_ctx = _make_mock_context()
        cm._register_popup_handler(1, mock_ctx)
        handler = mock_ctx._page_handlers[0]

        orphan = _FakePage(tab_id=None)
        managed = _FakePage(tab_id="real-tab-id")

        # 같은 event-loop turn에 두 핸들러 모두 호출
        handler(orphan)
        handler(managed)

        await asyncio.sleep(0.1)

        orphan.close.assert_called_once()
        managed.close.assert_not_called()

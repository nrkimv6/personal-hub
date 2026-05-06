"""
tests/services/ 공통 pytest fixture

SessionManager / TabPoolManager mock 조립의 단일 지점.
autouse fixture는 없으므로 다른 서비스 테스트에 부작용 없음.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture
def mock_playwright_page():
    """표준 mock playwright page를 반환한다."""
    page = MagicMock()
    page.goto = AsyncMock()
    page.content = AsyncMock(return_value="<html>로그인</html>")
    page.query_selector = AsyncMock(return_value=None)
    page.close = AsyncMock()
    page.evaluate = AsyncMock(return_value=None)
    return page


@pytest.fixture
def session_manager_with_mock_context(mock_playwright_page):
    """SessionManager + mock_context_manager + mock_context + mock_page 조립을 반환한다."""
    from app.shared.browser.session_manager import SessionManager

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_playwright_page)

    mock_context_manager = MagicMock()
    mock_context_manager._create_browser_context_visible = AsyncMock(return_value=mock_context)

    return SessionManager(mock_context_manager)


@pytest.fixture
def pool_factory():
    """factory: TabPoolManager 인스턴스를 반환한다."""
    def _factory(total_max=5):
        from app.shared.browser.tab_pool_manager import TabPoolManager
        mock_cm = MagicMock()
        with patch("app.shared.browser.tab_pool_manager.settings") as mock_s:
            mock_s.TAB_ROTATION_THRESHOLD = 100
            mock_s.CACHE_CLEANUP_INTERVAL = 300
            mock_s.TAB_REQUEST_TIMEOUT = 30
            mock_s.TAB_WAIT_RETRY_INTERVAL = 0.5
            mock_s.TOTAL_MAX_TABS = total_max
            mock_s.MAX_USES_PER_TAB = 50
            pool = TabPoolManager(mock_cm)
        return pool

    return _factory

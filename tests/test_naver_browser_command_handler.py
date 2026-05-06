"""NaverBrowserCommandHandler 단위 TC (RIGHT-BICEP)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker.naver_browser_command_handler import NaverBrowserCommandHandler


# ---- 헬퍼 ----

def _make_handler(browser=None):
    mock_bm = browser or MagicMock()
    return NaverBrowserCommandHandler(browser_manager=mock_bm, worker_name="test_worker")


def _make_command(cmd_type="open_browser", service_account_id=1, request_data=None):
    return {
        "id": 42,
        "command_type": cmd_type,
        "service_account_id": service_account_id,
        "request_data": request_data,
    }


# ---- Phase T1: _execute_browser_command dispatch ----

@pytest.mark.asyncio
async def test_execute_browser_command_open_browser_right():
    """R: cmd_type="open_browser" → _cmd_open_browser 호출."""
    handler = _make_handler()
    cmd = _make_command(cmd_type="open_browser")
    mock_fn = AsyncMock(return_value={"status": "opened", "url": "https://naver.com"})
    with patch.object(handler, "_cmd_open_browser", new=mock_fn):
        result = await handler._execute_browser_command(cmd)
        mock_fn.assert_called_once_with(cmd)
    assert result["status"] == "opened"


@pytest.mark.asyncio
async def test_execute_browser_command_naver_login_right():
    """R: cmd_type="naver_login" → _cmd_naver_login 호출."""
    handler = _make_handler()
    cmd = _make_command(cmd_type="naver_login")
    mock_fn = AsyncMock(return_value={"status": "login_page_opened"})
    with patch.object(handler, "_cmd_naver_login", new=mock_fn):
        await handler._execute_browser_command(cmd)
        mock_fn.assert_called_once_with(cmd)


@pytest.mark.asyncio
async def test_execute_browser_command_check_login_right():
    """R: cmd_type="naver_check_login" → _cmd_check_login 호출."""
    handler = _make_handler()
    cmd = _make_command(cmd_type="naver_check_login")
    mock_fn = AsyncMock(return_value={"logged_in": True})
    with patch.object(handler, "_cmd_check_login", new=mock_fn):
        await handler._execute_browser_command(cmd)
        mock_fn.assert_called_once_with(cmd)


@pytest.mark.asyncio
async def test_execute_browser_command_check_login_legacy_alias():
    """B: cmd_type="check_login" (레거시 alias) → _cmd_check_login 호출."""
    handler = _make_handler()
    cmd = _make_command(cmd_type="check_login")
    mock_fn = AsyncMock(return_value={"logged_in": False})
    with patch.object(handler, "_cmd_check_login", new=mock_fn):
        await handler._execute_browser_command(cmd)
        mock_fn.assert_called_once_with(cmd)


@pytest.mark.asyncio
async def test_execute_browser_command_unknown_error():
    """E: 알 수 없는 cmd_type → ValueError 발생."""
    handler = _make_handler()
    cmd = _make_command(cmd_type="unknown_cmd")
    with pytest.raises(ValueError, match="알 수 없는 명령"):
        await handler._execute_browser_command(cmd)


# ---- Phase T1: _cmd_open_browser ----

@pytest.mark.asyncio
async def test_cmd_open_browser_calls_execute_with_tab():
    """R: _cmd_open_browser → browser.execute_with_tab(operation_timeout=30.0)."""
    import json as _json
    mock_bm = MagicMock()
    mock_bm.execute_with_tab = AsyncMock(return_value=None)
    handler = _make_handler(browser=mock_bm)
    cmd = _make_command(cmd_type="open_browser", request_data=_json.dumps({"url": "https://naver.com"}))
    result = await handler._cmd_open_browser(cmd)
    mock_bm.execute_with_tab.assert_called_once()
    call_kwargs = mock_bm.execute_with_tab.call_args.kwargs
    assert call_kwargs["operation_timeout"] == 30.0
    assert call_kwargs["service_account_id"] == cmd["service_account_id"]
    assert result == {"status": "opened", "url": "https://naver.com"}


# ---- Phase T1: _cmd_close_browser ----

@pytest.mark.asyncio
async def test_cmd_close_browser_calls_context_manager():
    """R: _cmd_close_browser → browser.context_manager.close_context(service_account_id) 호출."""
    mock_ctx = MagicMock()
    mock_ctx.close_context = AsyncMock()
    mock_bm = MagicMock()
    mock_bm.context_manager = mock_ctx
    handler = _make_handler(browser=mock_bm)
    cmd = _make_command(cmd_type="close_browser", service_account_id=7)
    result = await handler._cmd_close_browser(cmd)
    mock_ctx.close_context.assert_called_once_with(7)
    assert result == {"status": "closed"}

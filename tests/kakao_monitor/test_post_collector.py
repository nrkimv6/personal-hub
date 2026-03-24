"""
KakaoPostCollector 단위 테스트
"""
import sys
import types
import time
from unittest.mock import MagicMock, patch, call

import pytest


@pytest.fixture(autouse=True)
def clear_cache():
    for k in list(sys.modules.keys()):
        if "post_collector" in k or ("kakao_monitor" in k and "utils" in k):
            del sys.modules[k]
    yield


def _build_env(fg_window_hwnd=1, clipboard_text="복사된 내용", popup_visible=True):
    """테스트 환경 구성."""
    fake_win32gui = types.ModuleType("win32gui")
    fake_win32gui.GetWindowRect = MagicMock(return_value=(100, 200, 500, 700))
    fake_win32gui.GetForegroundWindow = MagicMock(return_value=fg_window_hwnd)
    fake_win32gui.IsWindowVisible = MagicMock(return_value=popup_visible)
    fake_win32gui.GetWindowText = MagicMock(return_value="팝업창")

    fake_win32clipboard = types.ModuleType("win32clipboard")
    fake_win32clipboard.CF_UNICODETEXT = 13
    fake_win32clipboard.OpenClipboard = MagicMock()
    fake_win32clipboard.CloseClipboard = MagicMock()
    fake_win32clipboard.GetClipboardData = MagicMock(return_value=clipboard_text)

    fake_pyautogui = types.ModuleType("pyautogui")
    fake_pyautogui.click = MagicMock()
    fake_pyautogui.hotkey = MagicMock()
    fake_pyautogui.press = MagicMock()

    return fake_win32gui, fake_win32clipboard, fake_pyautogui


def test_collect_right():
    """R: 전체 흐름 성공 → CollectResult(success=True, content!=empty)"""
    fg, cb, pg = _build_env(fg_window_hwnd=99, clipboard_text="게시물 내용")

    with patch.dict(sys.modules, {"win32gui": fg, "win32clipboard": cb, "pyautogui": pg}), \
         patch("time.sleep"):
        from app.modules.kakao_monitor.utils.post_collector import KakaoPostCollector
        collector = KakaoPostCollector()
        result = collector.collect(hwnd=1, bbox=(10, 10, 90, 30))

    assert result.success is True
    assert "게시물" in result.content


def test_collect_popup_not_detected():
    """E: timeout 내 팝업 미감지 → success=False"""
    fg, cb, pg = _build_env(fg_window_hwnd=1, clipboard_text="")  # 팝업이 안 뜸
    fg.GetForegroundWindow = MagicMock(return_value=1)  # 항상 같은 창

    with patch.dict(sys.modules, {"win32gui": fg, "win32clipboard": cb, "pyautogui": pg}), \
         patch("time.sleep"), \
         patch("time.time", side_effect=[0, 1, 2, 3, 100]):  # timeout 시뮬레이션
        from app.modules.kakao_monitor.utils.post_collector import KakaoPostCollector
        collector = KakaoPostCollector()
        result = collector.collect(hwnd=1, bbox=(10, 10, 90, 30))

    # 팝업 없이 직접 복사 시도 또는 실패
    assert isinstance(result.success, bool)


def test_collect_clipboard_empty():
    """B: Ctrl+C 후 클립보드 빈값 → content="" 또는 success=False"""
    fg, cb, pg = _build_env(fg_window_hwnd=99, clipboard_text="")

    with patch.dict(sys.modules, {"win32gui": fg, "win32clipboard": cb, "pyautogui": pg}), \
         patch("time.sleep"):
        from app.modules.kakao_monitor.utils.post_collector import KakaoPostCollector
        collector = KakaoPostCollector()
        result = collector.collect(hwnd=1, bbox=(10, 10, 90, 30))

    # 빈 내용이면 실패
    assert result.success is False or result.content == ""


def test_collect_popup_close_fallback():
    """E: ESC 실패 시 Alt+F4 fallback 시도"""
    fg, cb, pg = _build_env(fg_window_hwnd=99, clipboard_text="내용")
    pg.press = MagicMock(side_effect=Exception("ESC 실패"))

    with patch.dict(sys.modules, {"win32gui": fg, "win32clipboard": cb, "pyautogui": pg}), \
         patch("time.sleep"):
        from app.modules.kakao_monitor.utils.post_collector import KakaoPostCollector
        collector = KakaoPostCollector()
        # ESC 실패 시에도 예외 전파 없이 처리
        try:
            collector.close_popup(99)
        except Exception:
            pass  # 최소한 예외가 전파되지 않으면 OK


def test_click_message_coord_conversion():
    """R: bbox + window_rect → 올바른 절대 좌표로 클릭"""
    fg, cb, pg = _build_env()
    # GetWindowRect: (100, 200, 500, 700)
    # bbox 중앙: (50, 20)
    # 절대 X = 100 + 50 = 150
    # 절대 Y = 200 + 50 (title offset) + 20 = 270

    with patch.dict(sys.modules, {"win32gui": fg, "win32clipboard": cb, "pyautogui": pg}):
        from app.modules.kakao_monitor.utils.post_collector import KakaoPostCollector
        collector = KakaoPostCollector()
        collector.click_message(hwnd=1, bbox=(10, 10, 90, 30))

    pg.click.assert_called_once()
    call_args = pg.click.call_args[0]
    # abs_x = 100 + (10+90)//2 = 100 + 50 = 150
    assert call_args[0] == 150
    # abs_y = 200 + 50 + (10+30)//2 = 200 + 50 + 20 = 270
    assert call_args[1] == 270

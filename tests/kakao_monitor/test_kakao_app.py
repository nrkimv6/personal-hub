"""
KakaoAppController 단위 테스트
"""
import sys
import types
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# psutil / win32 / pyautogui mock 설정 (Windows 전용 모듈 부재 대응)
# ---------------------------------------------------------------------------

def _make_fake_psutil(process_names: list[str]):
    """프로세스 이름 목록으로 fake psutil 생성."""
    mod = types.ModuleType("psutil")

    class FakeProc:
        def __init__(self, name):
            self.info = {"name": name}

    mod.process_iter = MagicMock(return_value=[FakeProc(n) for n in process_names])
    mod.NoSuchProcess = Exception
    mod.AccessDenied = Exception
    return mod


def _make_win32gui(windows: list[dict] | None = None):
    """fake win32gui 생성. windows = [{"title": ..., "class": ...}]"""
    mod = types.ModuleType("win32gui")
    windows = windows or []

    call_count = {"n": 0}
    hwnds = list(range(1, len(windows) + 1))

    def IsWindowVisible(hwnd):
        return True

    def GetClassName(hwnd):
        idx = hwnd - 1
        return windows[idx]["class"] if 0 <= idx < len(windows) else ""

    def GetWindowText(hwnd):
        idx = hwnd - 1
        return windows[idx]["title"] if 0 <= idx < len(windows) else ""

    def EnumWindows(callback, extra):
        for hwnd in hwnds:
            callback(hwnd, extra)

    def GetWindowRect(hwnd):
        return (100, 200, 500, 700)

    def GetForegroundWindow():
        return hwnds[0] if hwnds else 0

    def IsIconic(hwnd):
        return False

    def ShowWindow(hwnd, flag):
        pass

    def SetForegroundWindow(hwnd):
        pass

    def DeleteObject(handle):
        pass

    def ReleaseDC(hwnd, dc):
        pass

    mod.IsWindowVisible = IsWindowVisible
    mod.GetClassName = GetClassName
    mod.GetWindowText = GetWindowText
    mod.EnumWindows = EnumWindows
    mod.GetWindowRect = GetWindowRect
    mod.GetForegroundWindow = GetForegroundWindow
    mod.IsIconic = IsIconic
    mod.ShowWindow = ShowWindow
    mod.SetForegroundWindow = SetForegroundWindow
    mod.DeleteObject = DeleteObject
    mod.ReleaseDC = ReleaseDC
    return mod


def _make_win32con():
    mod = types.ModuleType("win32con")
    mod.SW_RESTORE = 9
    return mod


def _make_win32clipboard(chat_name_to_set: str = ""):
    mod = types.ModuleType("win32clipboard")
    mod.CF_UNICODETEXT = 13
    mod.OpenClipboard = MagicMock()
    mod.EmptyClipboard = MagicMock()
    mod.SetClipboardText = MagicMock()
    mod.CloseClipboard = MagicMock()
    return mod


def _make_pyautogui():
    mod = types.ModuleType("pyautogui")
    mod.click = MagicMock()
    mod.hotkey = MagicMock()
    mod.press = MagicMock()
    mod.typewrite = MagicMock()
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_module_cache():
    """kakao_app 유틸 모듈 캐시만 초기화 (models/routes 제외 — SQLAlchemy MetaData 충돌 방지)."""
    for key in list(sys.modules.keys()):
        if "kakao_app" in key:
            del sys.modules[key]
    yield


# ---------------------------------------------------------------------------
# is_running() 테스트
# ---------------------------------------------------------------------------

def test_is_running_right():
    """R: KakaoTalk.exe 프로세스 존재 시 True 반환."""
    fake_psutil = _make_fake_psutil(["chrome.exe", "KakaoTalk.exe", "notepad.exe"])
    with patch.dict(sys.modules, {"psutil": fake_psutil, "win32gui": MagicMock(),
                                   "win32con": MagicMock(), "win32clipboard": MagicMock(),
                                   "pyautogui": MagicMock()}):
        from app.modules.kakao_monitor.utils.kakao_app import KakaoAppController
        ctrl = KakaoAppController()
        assert ctrl.is_running() is True


def test_is_running_not_found():
    """E: 프로세스 미존재 시 False 반환."""
    fake_psutil = _make_fake_psutil(["chrome.exe", "notepad.exe"])
    with patch.dict(sys.modules, {"psutil": fake_psutil, "win32gui": MagicMock(),
                                   "win32con": MagicMock(), "win32clipboard": MagicMock(),
                                   "pyautogui": MagicMock()}):
        from app.modules.kakao_monitor.utils.kakao_app import KakaoAppController
        ctrl = KakaoAppController()
        assert ctrl.is_running() is False


def test_is_running_multiple_processes():
    """B: KakaoTalk.exe가 2개 이상 떠있어도 True."""
    fake_psutil = _make_fake_psutil(["KakaoTalk.exe", "KakaoTalk.exe"])
    with patch.dict(sys.modules, {"psutil": fake_psutil, "win32gui": MagicMock(),
                                   "win32con": MagicMock(), "win32clipboard": MagicMock(),
                                   "pyautogui": MagicMock()}):
        from app.modules.kakao_monitor.utils.kakao_app import KakaoAppController
        ctrl = KakaoAppController()
        assert ctrl.is_running() is True


# ---------------------------------------------------------------------------
# find_main_window() 테스트
# ---------------------------------------------------------------------------

def test_find_main_window_right():
    """R: EVA_Window 클래스 창 발견 시 hwnd 반환."""
    windows = [{"title": "오픈채팅방", "class": "EVA_Window_Dblclk"}]
    fake_win32gui = _make_win32gui(windows)
    with patch.dict(sys.modules, {"psutil": MagicMock(), "win32gui": fake_win32gui,
                                   "win32con": _make_win32con(), "win32clipboard": MagicMock(),
                                   "pyautogui": MagicMock()}):
        from app.modules.kakao_monitor.utils.kakao_app import KakaoAppController
        ctrl = KakaoAppController()
        hwnd = ctrl.find_main_window()
        assert hwnd == 1


def test_find_main_window_not_found():
    """E: 카카오톡 창 없을 때 None 반환."""
    windows = [{"title": "메모장", "class": "Notepad"}]
    fake_win32gui = _make_win32gui(windows)
    with patch.dict(sys.modules, {"psutil": MagicMock(), "win32gui": fake_win32gui,
                                   "win32con": _make_win32con(), "win32clipboard": MagicMock(),
                                   "pyautogui": MagicMock()}):
        from app.modules.kakao_monitor.utils.kakao_app import KakaoAppController
        ctrl = KakaoAppController()
        assert ctrl.find_main_window() is None


def test_find_main_window_multiple():
    """B: 여러 카카오톡 창 존재 시 첫 번째 반환."""
    windows = [
        {"title": "채팅방 A", "class": "EVA_Window_Dblclk"},
        {"title": "채팅방 B", "class": "EVA_Window"},
    ]
    fake_win32gui = _make_win32gui(windows)
    with patch.dict(sys.modules, {"psutil": MagicMock(), "win32gui": fake_win32gui,
                                   "win32con": _make_win32con(), "win32clipboard": MagicMock(),
                                   "pyautogui": MagicMock()}):
        from app.modules.kakao_monitor.utils.kakao_app import KakaoAppController
        ctrl = KakaoAppController()
        hwnd = ctrl.find_main_window()
        assert hwnd == 1


# ---------------------------------------------------------------------------
# navigate_to_chat() 테스트
# ---------------------------------------------------------------------------

def _setup_navigate_mocks(chat_name: str, verify_result: bool = True):
    """navigate_to_chat 테스트용 mock 세팅."""
    windows = [{"title": chat_name, "class": "EVA_Window_Dblclk"}]
    fake_win32gui = _make_win32gui(windows)
    # GetForegroundWindow 진입 확인용 — 성공이면 chat_name이 title인 창 반환
    fake_win32gui.GetForegroundWindow = MagicMock(return_value=1 if verify_result else 999)
    fake_pyautogui = _make_pyautogui()
    fake_win32clipboard = _make_win32clipboard(chat_name)
    return fake_win32gui, fake_pyautogui, fake_win32clipboard


def test_navigate_to_chat_right():
    """R: 전체 채팅방 진입 흐름 성공 → True."""
    chat_name = "테스트채팅방"
    fg, pg, cb = _setup_navigate_mocks(chat_name, verify_result=True)
    with patch.dict(sys.modules, {"psutil": MagicMock(), "win32gui": fg,
                                   "win32con": _make_win32con(), "win32clipboard": cb,
                                   "pyautogui": pg}), \
         patch("time.sleep"):
        from app.modules.kakao_monitor.utils.kakao_app import KakaoAppController
        ctrl = KakaoAppController()
        result = ctrl.navigate_to_chat(chat_name)
        assert result is True
        pg.hotkey.assert_any_call("ctrl", "f")
        pg.hotkey.assert_any_call("ctrl", "v")


def test_navigate_to_chat_retry_then_success():
    """B: 1~2회 실패 후 3회차 성공 → True."""
    chat_name = "성공채팅방"
    windows = [{"title": chat_name, "class": "EVA_Window_Dblclk"}]
    fg = _make_win32gui(windows)
    call_count = {"n": 0}
    def fg_window():
        call_count["n"] += 1
        # 3번째 호출부터 성공
        return 1 if call_count["n"] >= 3 else 999
    fg.GetForegroundWindow = MagicMock(side_effect=fg_window)
    pg = _make_pyautogui()
    cb = _make_win32clipboard(chat_name)
    with patch.dict(sys.modules, {"psutil": MagicMock(), "win32gui": fg,
                                   "win32con": _make_win32con(), "win32clipboard": cb,
                                   "pyautogui": pg}), \
         patch("time.sleep"):
        from app.modules.kakao_monitor.utils.kakao_app import KakaoAppController
        ctrl = KakaoAppController()
        result = ctrl.navigate_to_chat(chat_name)
        assert result is True


def test_navigate_to_chat_all_retries_fail():
    """B: 3회 모두 실패 → False."""
    chat_name = "실패채팅방"
    windows = [{"title": "다른방", "class": "EVA_Window_Dblclk"}]
    fg = _make_win32gui(windows)
    fg.GetForegroundWindow = MagicMock(return_value=999)
    pg = _make_pyautogui()
    cb = _make_win32clipboard(chat_name)
    with patch.dict(sys.modules, {"psutil": MagicMock(), "win32gui": fg,
                                   "win32con": _make_win32con(), "win32clipboard": cb,
                                   "pyautogui": pg}), \
         patch("time.sleep"):
        from app.modules.kakao_monitor.utils.kakao_app import KakaoAppController
        ctrl = KakaoAppController()
        result = ctrl.navigate_to_chat(chat_name)
        assert result is False


def test_navigate_to_chat_clipboard_error():
    """E: win32clipboard 오류 시 예외 전파 안 됨 (graceful fail)."""
    chat_name = "채팅방"
    windows = [{"title": chat_name, "class": "EVA_Window_Dblclk"}]
    fg = _make_win32gui(windows)
    fg.GetForegroundWindow = MagicMock(return_value=1)
    pg = _make_pyautogui()
    cb = _make_win32clipboard(chat_name)
    cb.OpenClipboard = MagicMock(side_effect=Exception("클립보드 오류"))
    with patch.dict(sys.modules, {"psutil": MagicMock(), "win32gui": fg,
                                   "win32con": _make_win32con(), "win32clipboard": cb,
                                   "pyautogui": pg}), \
         patch("time.sleep"):
        from app.modules.kakao_monitor.utils.kakao_app import KakaoAppController
        ctrl = KakaoAppController()
        # 예외 전파 없이 실행 완료
        result = ctrl.navigate_to_chat(chat_name)
        assert isinstance(result, bool)


def test_navigate_to_chat_no_search_results():
    """E: 검색 결과 0건 (진입 확인 실패) → 재시도 후 False."""
    chat_name = "미존재채팅방"
    windows = [{"title": "다른방", "class": "EVA_Window_Dblclk"}]
    fg = _make_win32gui(windows)
    fg.GetForegroundWindow = MagicMock(return_value=999)
    pg = _make_pyautogui()
    cb = _make_win32clipboard(chat_name)
    with patch.dict(sys.modules, {"psutil": MagicMock(), "win32gui": fg,
                                   "win32con": _make_win32con(), "win32clipboard": cb,
                                   "pyautogui": pg}), \
         patch("time.sleep"):
        from app.modules.kakao_monitor.utils.kakao_app import KakaoAppController
        ctrl = KakaoAppController()
        result = ctrl.navigate_to_chat(chat_name)
        assert result is False

"""
카카오톡 앱 컨트롤러 — 프로세스 탐지 + 창 핸들 + 채팅방 진입.

Notes:
    - 한글 입력은 pyautogui.typewrite 미지원이므로 클립보드 방식 사용.
    - v1: 단일 채팅방 감시 전용. 멀티 채팅방 전환은 v2.
"""
import logging
import time

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore

try:
    import win32gui
    import win32con
    import win32clipboard
except ImportError:
    win32gui = None  # type: ignore
    win32con = None  # type: ignore
    win32clipboard = None  # type: ignore

try:
    import pyautogui
except ImportError:
    pyautogui = None  # type: ignore

logger = logging.getLogger(__name__)

# 카카오톡 PC 알려진 윈도우 클래스명
_KAKAO_CLASSES = ["EVA_Window_Dblclk", "EVA_Window", "#32770"]
_KAKAO_PROCESS_NAME = "KakaoTalk.exe"

# 채팅방 진입 재시도
MAX_RETRIES = 3
SEARCH_OPEN_DELAY = 0.5   # 검색창 열린 후 대기
RESULT_CLICK_DELAY = 0.5  # 결과 클릭 후 대기


class KakaoAppController:
    """카카오톡 프로세스 확인, 창 핸들 탐색, 채팅방 진입 담당."""

    # ------------------------------------------------------------------ #
    # 프로세스 / 창 탐색
    # ------------------------------------------------------------------ #

    def is_running(self) -> bool:
        """KakaoTalk.exe 프로세스 존재 여부 반환."""
        if psutil is None:
            logger.warning("psutil 미설치 — is_running() 항상 False 반환")
            return False
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"] == _KAKAO_PROCESS_NAME:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

    def find_main_window(self) -> int | None:
        """카카오톡 메인 창 핸들 반환. 미발견 시 None.

        탐색 순서: EVA_Window_Dblclk → EVA_Window → #32770
        stale handle 완화 기준:
            - IsWindowVisible=True 이고
            - class/title 조건을 만족하는 첫 번째 hwnd를 채택한다.
        """
        if win32gui is None:
            logger.warning("win32gui 미설치 — find_main_window() None 반환")
            return None

        found: list[int] = []

        def _callback(hwnd: int, _) -> bool:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            class_name = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd)
            if title and any(cls in class_name for cls in _KAKAO_CLASSES):
                found.append(hwnd)
            return True

        win32gui.EnumWindows(_callback, None)

        if not found:
            logger.debug("카카오톡 창을 찾지 못했습니다.")
            return None

        # 가장 처음 발견된 핸들 반환 (일반적으로 메인 창)
        hwnd = found[0]
        logger.debug("카카오톡 창 핸들: 0x%08X (%s)", hwnd, win32gui.GetWindowText(hwnd))
        return hwnd

    def find_window_by_title(self, chat_name: str) -> int | None:
        """채팅방 이름으로 창 핸들 탐색 (부분 일치). 미발견 시 None."""
        if win32gui is None:
            return None

        found: list[int] = []

        def _callback(hwnd: int, _) -> bool:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            class_name = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd)
            if chat_name in title and any(cls in class_name for cls in _KAKAO_CLASSES):
                found.append(hwnd)
            return True

        win32gui.EnumWindows(_callback, None)
        return found[0] if found else None

    def get_window_rect(self, hwnd: int) -> tuple[int, int, int, int]:
        """창 위치/크기 반환 (left, top, right, bottom)."""
        if win32gui is None:
            return (0, 0, 0, 0)
        return win32gui.GetWindowRect(hwnd)

    # ------------------------------------------------------------------ #
    # 채팅방 진입
    # ------------------------------------------------------------------ #

    def navigate_to_chat(self, chat_name: str) -> bool:
        """검색창 기반 채팅방 진입.

        흐름:
            1. 메인 창 전경으로 가져오기
            2. Ctrl+F (검색창 열기)
            3. 클립보드로 chat_name 붙여넣기
            4. 첫 번째 검색 결과 클릭
            5. 진입 확인 (제목바 텍스트 포함 여부)

        Returns:
            True if successfully navigated, False otherwise.
        """
        if win32gui is None or pyautogui is None:
            logger.error("win32gui 또는 pyautogui 미설치 — navigate_to_chat 불가")
            return False

        hwnd = self.find_main_window()
        if hwnd is None:
            logger.error("카카오톡 메인 창을 찾지 못했습니다.")
            return False

        for attempt in range(1, MAX_RETRIES + 1):
            logger.info("채팅방 진입 시도 %d/%d: %r", attempt, MAX_RETRIES, chat_name)
            try:
                success = self._try_navigate(hwnd, chat_name)
                if success:
                    logger.info("채팅방 진입 성공: %r", chat_name)
                    return True
            except Exception as exc:
                logger.warning("채팅방 진입 실패 (시도 %d): %s", attempt, exc)

            # 실패 시 ESC로 검색창 닫고 재시도
            pyautogui.press("escape")
            time.sleep(0.3)

        logger.error("채팅방 진입 최종 실패: %r", chat_name)
        return False

    def _try_navigate(self, hwnd: int, chat_name: str) -> bool:
        """단일 채팅방 진입 시도."""
        # 1. 창 전경으로 가져오기
        self._bring_to_foreground(hwnd)
        time.sleep(0.2)

        # 2. 검색창 열기 (Ctrl+F)
        pyautogui.hotkey("ctrl", "f")
        time.sleep(SEARCH_OPEN_DELAY)

        # 3. 한글 입력 — 클립보드 붙여넣기
        self._type_korean(chat_name)
        time.sleep(SEARCH_OPEN_DELAY)

        # 4. 검색 결과 첫 번째 항목 클릭
        rect = self.get_window_rect(hwnd)
        win_left, win_top, win_right, win_bottom = rect
        win_width = win_right - win_left
        win_height = win_bottom - win_top

        # 검색 결과 패널은 창 좌측 ~240px 너비, 상단 ~120px 아래부터 시작
        result_x = win_left + min(120, win_width // 2)
        result_y = win_top + min(150, win_height // 3)
        pyautogui.click(result_x, result_y)
        time.sleep(RESULT_CLICK_DELAY)

        # 5. 진입 확인
        return self._verify_chat_entry(chat_name)

    def _bring_to_foreground(self, hwnd: int) -> None:
        """창을 전경으로 가져옵니다."""
        if win32gui is None or win32con is None:
            return
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        except Exception as exc:
            logger.debug("SetForegroundWindow 실패: %s", exc)

    def _type_korean(self, text: str) -> None:
        """클립보드를 통해 한글 텍스트 입력."""
        if win32clipboard is None or pyautogui is None:
            return
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
        except Exception as exc:
            logger.warning("클립보드 설정 실패: %s", exc)
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
            return
        pyautogui.hotkey("ctrl", "v")

    def _verify_chat_entry(self, chat_name: str) -> bool:
        """현재 포그라운드 창 제목에 chat_name 포함 여부 확인."""
        if win32gui is None:
            return True  # 검증 불가 시 성공으로 간주
        try:
            fg_hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(fg_hwnd)
            result = chat_name in title
            logger.debug("진입 확인: title=%r, chat_name=%r, match=%s", title, chat_name, result)
            return result
        except Exception as exc:
            logger.debug("진입 확인 실패: %s", exc)
            return False

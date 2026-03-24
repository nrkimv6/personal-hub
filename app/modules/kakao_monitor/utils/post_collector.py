"""
게시물 클릭 & 내용 복사 자동화.

흐름:
    click_message() → wait_for_popup() → copy_content() → close_popup()
    collect()로 전체 흐름 통합.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

try:
    import win32gui
    import win32clipboard
except ImportError:
    win32gui = None  # type: ignore
    win32clipboard = None  # type: ignore

try:
    import pyautogui
except ImportError:
    pyautogui = None  # type: ignore

# 채팅 영역 상단 오프셋 (KakaoCaptureUtil._TITLE_BAR_HEIGHT와 일치)
_CHAT_AREA_TOP_OFFSET = 50


@dataclass
class CollectResult:
    """게시물 수집 결과."""
    success: bool
    content: str = ""
    screenshot_path: str | None = None
    error: str | None = None
    extra: dict = field(default_factory=dict)


class KakaoPostCollector:
    """메시지 클릭 → 팝업 복사 → 닫기 자동화."""

    def collect(self, hwnd: int, bbox: tuple) -> CollectResult:
        """전체 수집 흐름 실행.

        Args:
            hwnd: 카카오톡 채팅방 창 핸들
            bbox: OCR 인식된 메시지의 (x1, y1, x2, y2) 상대 좌표 (채팅 영역 기준)

        Returns:
            CollectResult
        """
        try:
            # 1. 메시지 클릭
            self.click_message(hwnd, bbox)

            # 2. 팝업 대기
            popup_hwnd = self.wait_for_popup(original_hwnd=hwnd)
            if popup_hwnd is None:
                logger.warning("팝업 창 미감지 — 클릭만으로 내용 복사 시도")
                # 팝업 없이 직접 복사 시도
                content = self._copy_without_popup()
                if content:
                    return CollectResult(success=True, content=content)
                return CollectResult(success=False, error="팝업 창 미감지")

            # 3. 내용 복사
            content = self.copy_content(popup_hwnd)

            # 4. 팝업 닫기
            self.close_popup(popup_hwnd)

            if content:
                return CollectResult(success=True, content=content)
            return CollectResult(success=False, error="복사 내용 없음")

        except Exception as exc:
            logger.exception("수집 실패: %s", exc)
            return CollectResult(success=False, error=str(exc))

    def click_message(self, hwnd: int, bbox: tuple) -> None:
        """OCR bbox를 윈도우 절대 좌표로 변환 후 클릭.

        Args:
            hwnd: 창 핸들
            bbox: (x1, y1, x2, y2) 채팅 영역 내 상대 좌표
        """
        if win32gui is None or pyautogui is None:
            logger.error("win32gui 또는 pyautogui 미설치")
            return

        rect = win32gui.GetWindowRect(hwnd)
        win_left, win_top = rect[0], rect[1]

        # bbox 중앙 좌표 (채팅 영역 상대)
        x1, y1, x2, y2 = bbox
        rel_x = (x1 + x2) // 2
        rel_y = (y1 + y2) // 2

        # 절대 좌표 = 창 위치 + 채팅 영역 오프셋 + 상대 좌표
        abs_x = win_left + rel_x
        abs_y = win_top + _CHAT_AREA_TOP_OFFSET + rel_y

        logger.debug("메시지 클릭: abs=(%d, %d)", abs_x, abs_y)
        pyautogui.click(abs_x, abs_y)

    def wait_for_popup(
        self,
        original_hwnd: int,
        timeout: float = 3.0,
    ) -> int | None:
        """팝업 창(새 포그라운드 창) 출현 대기.

        Args:
            original_hwnd: 클릭 전 기준 창 핸들
            timeout: 대기 시간 (초)

        Returns:
            팝업 hwnd or None
        """
        if win32gui is None:
            return None

        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.3)
            try:
                fg_hwnd = win32gui.GetForegroundWindow()
                if fg_hwnd != original_hwnd and win32gui.IsWindowVisible(fg_hwnd):
                    title = win32gui.GetWindowText(fg_hwnd)
                    logger.debug("팝업 감지: hwnd=0x%X title=%r", fg_hwnd, title)
                    return fg_hwnd
            except Exception:
                pass

        return None

    def copy_content(self, popup_hwnd: int) -> str:
        """팝업 창에서 전체 선택 후 클립보드로 복사.

        Args:
            popup_hwnd: 팝업 창 핸들

        Returns:
            복사된 텍스트 (빈 문자열이면 실패)
        """
        if pyautogui is None or win32clipboard is None:
            return ""

        try:
            # 전체 선택 + 복사
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.2)
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.3)

            # 클립보드 읽기
            win32clipboard.OpenClipboard()
            try:
                data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()

            logger.debug("복사 내용 길이: %d자", len(data) if data else 0)
            return data or ""

        except Exception as exc:
            logger.exception("내용 복사 실패: %s", exc)
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
            return ""

    def close_popup(self, popup_hwnd: int) -> None:
        """팝업 창 닫기 (ESC → 실패 시 Alt+F4)."""
        if pyautogui is None:
            return
        try:
            pyautogui.press("escape")
            time.sleep(0.2)
        except Exception:
            pass

        # ESC로 안 닫힌 경우 Alt+F4
        if win32gui is not None:
            try:
                if win32gui.IsWindowVisible(popup_hwnd):
                    pyautogui.hotkey("alt", "F4")
            except Exception as exc:
                logger.debug("Alt+F4 실패: %s", exc)

    def _copy_without_popup(self) -> str:
        """팝업 없을 때 현재 창에서 직접 복사 시도."""
        if pyautogui is None or win32clipboard is None:
            return ""
        try:
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.2)
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.3)
            win32clipboard.OpenClipboard()
            try:
                data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
            return data or ""
        except Exception:
            return ""

"""
화면 캡처 유틸 — 창 직접 캡처 (포그라운드 전환 불필요).

캡처 방법: GetWindowDC + PrintWindow (백그라운드 동작 가능)
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

try:
    import win32gui
    import win32con
    import win32ui
    from ctypes import windll
except ImportError:
    win32gui = None  # type: ignore
    win32con = None  # type: ignore
    win32ui = None  # type: ignore
    windll = None  # type: ignore

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore

# 채팅 영역에서 제외할 픽셀 높이
_TITLE_BAR_HEIGHT = 50    # 상단 타이틀바
_INPUT_BOX_HEIGHT = 100   # 하단 입력창


class KakaoCaptureUtil:
    """카카오톡 창 캡처 전담 유틸."""

    def capture_window(self, hwnd: int, region: tuple | None = None) -> object | None:
        """창 전체 (또는 region 영역) 캡처.

        Args:
            hwnd: 창 핸들
            region: (left, top, right, bottom) 상대 좌표. None이면 전체.

        Returns:
            PIL.Image or None
        """
        if win32gui is None or Image is None:
            logger.error("win32gui 또는 Pillow 미설치")
            return None

        try:
            # 최소화 복원
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                time.sleep(0.3)

            rect = win32gui.GetWindowRect(hwnd)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]

            if width <= 0 or height <= 0:
                logger.warning("창 크기가 유효하지 않습니다: %dx%d", width, height)
                return None

            # DC 설정
            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            save_bitmap = win32ui.CreateBitmap()
            save_bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(save_bitmap)

            # PrintWindow: 포그라운드 전환 없이 캡처
            result = windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)
            if result == 0:
                # fallback: BitBlt
                save_dc.BitBlt((0, 0), (width, height), mfc_dc, (0, 0), win32con.SRCCOPY)

            bmp_info = save_bitmap.GetInfo()
            bmp_str = save_bitmap.GetBitmapBits(True)

            img = Image.frombuffer(
                "RGB",
                (bmp_info["bmWidth"], bmp_info["bmHeight"]),
                bmp_str,
                "raw",
                "BGRX",
                0,
                1,
            )

            # 리소스 정리
            win32gui.DeleteObject(save_bitmap.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)

            if region is not None:
                img = img.crop(region)

            return img

        except Exception as exc:
            logger.exception("캡처 실패 (hwnd=0x%X): %s", hwnd, exc)
            return None

    def capture_chat_area(self, hwnd: int) -> object | None:
        """채팅 내용 영역만 캡처 (타이틀바/입력창 제외).

        Returns:
            PIL.Image or None
        """
        if win32gui is None:
            return None

        rect = win32gui.GetWindowRect(hwnd)
        win_width = rect[2] - rect[0]
        win_height = rect[3] - rect[1]

        top = _TITLE_BAR_HEIGHT
        bottom = win_height - _INPUT_BOX_HEIGHT
        if bottom <= top:
            logger.warning("창이 너무 작아 채팅 영역 캡처 불가: %dx%d", win_width, win_height)
            return None

        region = (0, top, win_width, bottom)
        return self.capture_window(hwnd, region=region)

"""
워커 제어 & 카카오톡 창 탐색 API.
"""
from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.kakao_monitor import KakaoWatchConfig
from app.modules.kakao_monitor.utils.kakao_app import KakaoAppController

router = APIRouter(prefix="/api/v1/kakao-monitor", tags=["kakao-monitor"])

KAKAO_SCAN_QUEUE = "kakao:scan_queue"


# ========== Schemas ==========

class WorkerStatus(BaseModel):
    is_kakao_running: bool
    main_window_found: bool
    active_config_count: int


class WindowInfo(BaseModel):
    hwnd: int
    title: str
    hwnd_hex: str


class ScanTriggerResponse(BaseModel):
    queued: bool
    message: str


# ========== Routes ==========

@router.get("/status", response_model=WorkerStatus)
def get_status(db: Session = Depends(get_db)):
    ctrl = KakaoAppController()
    is_running = ctrl.is_running()
    hwnd = ctrl.find_main_window() if is_running else None
    active_count = (
        db.query(KakaoWatchConfig)
        .filter(KakaoWatchConfig.is_active.is_(True))
        .count()
    )
    return WorkerStatus(
        is_kakao_running=is_running,
        main_window_found=hwnd is not None,
        active_config_count=active_count,
    )


@router.post("/scan", response_model=ScanTriggerResponse)
async def trigger_scan():
    """수동 1회 스캔 트리거 — Redis 큐에 scan 명령 push."""
    try:
        from app.shared.redis import get_redis
        redis_client = await get_redis()
        if redis_client is None:
            return ScanTriggerResponse(queued=False, message="Redis 클라이언트 없음")
        payload = json.dumps({"action": "scan"})
        await redis_client.rpush(KAKAO_SCAN_QUEUE, payload)
        return ScanTriggerResponse(queued=True, message="스캔 요청 큐에 추가됨")
    except Exception as exc:
        return ScanTriggerResponse(queued=False, message=str(exc))


@router.get("/windows", response_model=List[WindowInfo])
def get_windows():
    """열려 있는 카카오톡 창 목록 반환."""
    try:
        import win32gui

        windows: list[WindowInfo] = []
        _KAKAO_CLASSES = ["EVA_Window_Dblclk", "EVA_Window", "#32770"]

        def _callback(hwnd: int, _) -> bool:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            class_name = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd)
            if title and any(cls in class_name for cls in _KAKAO_CLASSES):
                windows.append(WindowInfo(
                    hwnd=hwnd,
                    title=title,
                    hwnd_hex=f"0x{hwnd:08X}",
                ))
            return True

        win32gui.EnumWindows(_callback, None)
        return windows
    except ImportError:
        raise HTTPException(status_code=503, detail="win32gui 미설치 (Windows 전용)")

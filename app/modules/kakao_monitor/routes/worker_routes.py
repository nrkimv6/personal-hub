"""워커 제어 & 카카오톡 창 탐색 API."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.kakao_monitor import KakaoWatchConfig
from app.modules.kakao_monitor.runtime_status import get_runtime_status
from app.modules.kakao_monitor.utils.kakao_app import KakaoAppController

router = APIRouter(prefix="/api/v1/kakao-monitor", tags=["kakao-monitor"])

# Deprecated: worker에서 scan queue를 소비하지 않는다.
KAKAO_SCAN_QUEUE = "kakao:scan_queue"


# ========== Schemas ==========

class WorkerStatus(BaseModel):
    is_kakao_running: bool
    main_window_found: bool
    active_config_count: int
    worker_registered: bool
    last_loop_at: Optional[str]
    last_error: Optional[str]
    loop_interval_sec: Optional[float]
    status_message: Optional[str]


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

    runtime = get_runtime_status()
    status_message = runtime.get("idle_reason")
    if active_count == 0:
        status_message = "idle(no active config)"
    if not is_running:
        status_message = "kakao process not running"
    if runtime.get("registration_error"):
        status_message = runtime.get("registration_error")

    return WorkerStatus(
        is_kakao_running=is_running,
        main_window_found=hwnd is not None,
        active_config_count=active_count,
        worker_registered=bool(runtime.get("worker_registered")),
        last_loop_at=runtime.get("last_loop_at"),
        last_error=runtime.get("last_error"),
        loop_interval_sec=runtime.get("loop_interval_sec"),
        status_message=status_message,
    )


@router.post("/scan", response_model=ScanTriggerResponse)
async def trigger_scan():
    """수동 scan API.

    scan queue consumer가 없는 상태에서 queue push-only 동작은 no-op이므로,
    명시적으로 deprecated 응답을 반환한다.
    """
    return ScanTriggerResponse(
        queued=False,
        message="scan queue deprecated: no consumer. worker loop performs automatic scans",
    )


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

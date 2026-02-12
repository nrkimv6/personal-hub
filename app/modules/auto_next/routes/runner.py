"""실행 제어 API"""

from fastapi import APIRouter

from app.modules.auto_next.schemas import RunRequest, RunStatusResponse
from app.modules.auto_next.services.executor_service import executor_service

router = APIRouter()


@router.post("/run", response_model=RunStatusResponse)
async def start_run(request: RunRequest):
    """auto-next 실행 시작"""
    return executor_service.start_auto_next(request)


@router.post("/stop")
async def stop_run():
    """auto-next 실행 중지"""
    return executor_service.stop_auto_next()


@router.get("/status", response_model=RunStatusResponse)
async def get_status():
    """실행 상태 조회"""
    return executor_service.get_process_status()


@router.post("/reset-state")
async def reset_state():
    """RUNNING 상태 강제 초기화 (비정상 종료 후 복구)"""
    return executor_service.reset_running_state()


__all__ = ['router']

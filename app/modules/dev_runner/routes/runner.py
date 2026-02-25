"""실행 제어 API"""

from fastapi import APIRouter

from app.modules.dev_runner.schemas import RunRequest, RunStatusResponse
from app.modules.dev_runner.services.executor_service import executor_service

router = APIRouter()


@router.post("/run", response_model=RunStatusResponse)
async def start_run(request: RunRequest):
    """plan-runner 실행 시작"""
    return await executor_service.start_dev_runner(request)


@router.post("/stop")
async def stop_run():
    """plan-runner 실행 중지"""
    return await executor_service.stop_dev_runner()


@router.get("/status", response_model=RunStatusResponse)
async def get_status():
    """실행 상태 조회"""
    return executor_service.get_process_status()


@router.post("/reset-state")
async def reset_state(full_reset: bool = False):
    """RUNNING 상태 강제 초기화 (비정상 종료 후 복구). full_reset=true이면 모든 작업 삭제"""
    return executor_service.reset_running_state(full_reset=full_reset)


@router.post("/restart-listener")
def restart_listener():
    """command-listener 프로세스 재시작"""
    return executor_service.restart_listener()


__all__ = ['router']

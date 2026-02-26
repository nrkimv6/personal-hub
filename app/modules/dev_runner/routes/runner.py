"""실행 제어 API"""

import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException

from app.modules.dev_runner.schemas import RunRequest, RunStatusResponse, RunnerListItem, MergeQueueItem, MergeStatusResponse
from app.modules.dev_runner.services.executor_service import executor_service

router = APIRouter()


@router.get("/runners", response_model=list[RunnerListItem])
async def list_runners():
    """모든 active runner 목록 조회"""
    return executor_service.get_all_runners()


@router.post("/runners/{runner_id}/stop")
async def stop_runner(runner_id: str):
    """특정 runner 중지"""
    return await executor_service.stop_dev_runner(runner_id)


@router.post("/run", response_model=RunStatusResponse)
async def start_run(request: RunRequest):
    """plan-runner 실행 시작"""
    return await executor_service.start_dev_runner(request)


@router.post("/stop")
async def stop_run():
    """plan-runner 실행 중지 (하위호환 — 첫 번째 active runner 종료)"""
    runners = executor_service.get_all_runners()
    if not runners:
        return {"message": "Not running"}
    return await executor_service.stop_dev_runner(runners[0].runner_id)


@router.get("/status", response_model=RunStatusResponse)
async def get_status():
    """실행 상태 조회 (하위호환 — 첫 번째 active runner)"""
    return executor_service.get_process_status()


@router.post("/reset-state")
async def reset_state(full_reset: bool = False):
    """RUNNING 상태 강제 초기화 (비정상 종료 후 복구). full_reset=true이면 모든 작업 삭제"""
    return executor_service.reset_running_state(full_reset=full_reset)


@router.post("/restart-listener")
def restart_listener():
    """command-listener 프로세스 재시작"""
    return executor_service.restart_listener()


@router.post("/runners/{runner_id}/retry-merge")
async def retry_merge(runner_id: str):
    """머지 충돌 후 재머지 시도"""
    return await executor_service.send_runner_command(runner_id, "retry-merge")


@router.delete("/runners/{runner_id}/worktree")
async def cleanup_worktree(runner_id: str):
    """runner worktree 수동 정리"""
    return await executor_service.send_runner_command(runner_id, "cleanup-worktree")


@router.get("/merge-queue", response_model=list[MergeQueueItem])
async def get_merge_queue():
    """Merge Queue 목록 조회"""
    return await executor_service.get_merge_queue()


@router.get("/merge/{runner_id}", response_model=MergeStatusResponse)
async def get_merge_status(runner_id: str):
    """특정 runner의 merge 상태 조회"""
    status = await executor_service.get_merge_status(runner_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"merge status not found for runner {runner_id}")
    return status


@router.post("/merge/{runner_id}/retry")
async def retry_merge_request(runner_id: str):
    """Merge 재시도 요청"""
    return await executor_service.send_runner_command(runner_id, "retry-merge")


@router.post("/merge/{runner_id}/revert")
async def revert_merge_request(runner_id: str):
    """Merge 되돌리기 요청"""
    return await executor_service.send_runner_command(runner_id, "revert-merge")


__all__ = ['router']

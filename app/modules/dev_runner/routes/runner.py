"""실행 제어 API"""

import asyncio
import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException

from app.modules.dev_runner.schemas import RunRequest, RunStatusResponse, RunnerListItem, MergeQueueItem, MergeStatusResponse, MergeHistoryItem, MergeQueueEnqueueRequest, DirectMergeRequest, RetryMergeRequest
from app.modules.dev_runner.services.executor_service import executor_service

router = APIRouter()


@router.get("/runners", response_model=list[RunnerListItem])
async def list_runners():
    """모든 active runner 목록 조회"""
    return await executor_service.get_all_runners()


@router.post("/runners/{runner_id}/stop")
async def stop_runner(runner_id: str):
    """특정 runner 중지"""
    return await executor_service.stop_dev_runner(runner_id)


@router.post("/run", response_model=RunStatusResponse)
async def start_run(request: RunRequest):
    """plan-runner 실행 시작"""
    return await executor_service.start_dev_runner(request)


@router.post("/stop-all")
async def stop_all_runners():
    """모든 active runner 일괄 중지"""
    return await executor_service.stop_all_runners()


@router.post("/stop")
async def stop_run():
    """plan-runner 실행 중지 (하위호환 — 첫 번째 active runner 종료)"""
    runners = await executor_service.get_all_runners()
    if not runners:
        return {"message": "Not running"}
    return await executor_service.stop_dev_runner(runners[0].runner_id)


@router.get("/status", response_model=RunStatusResponse)
async def get_status():
    """실행 상태 조회 (하위호환 — 첫 번째 active runner)"""
    return await executor_service.get_process_status()


@router.post("/reset-state")
async def reset_state(full_reset: bool = False):
    """RUNNING 상태 강제 초기화 (비정상 종료 후 복구). full_reset=true이면 모든 작업 삭제"""
    return await executor_service.reset_running_state(full_reset=full_reset)


@router.post("/restart-listener")
async def restart_listener():
    """command-listener 프로세스 재시작"""
    return await asyncio.to_thread(executor_service.restart_listener)


@router.post("/runners/{runner_id}/kill")
async def kill_runner(runner_id: str):
    """특정 runner 강제 종료 (SIGKILL — 진행 중인 작업이 유실될 수 있음)"""
    return await executor_service.send_runner_command(runner_id, "force-kill")


@router.post("/runners/{runner_id}/retry-merge")
async def retry_merge(runner_id: str):
    """머지 충돌 후 재머지 시도"""
    return await executor_service.send_runner_command(runner_id, "retry-merge")


@router.delete("/runners/{runner_id}/worktree")
async def cleanup_worktree(runner_id: str):
    """runner worktree 수동 정리"""
    return await executor_service.send_runner_command(runner_id, "cleanup-worktree")


@router.delete("/runners/{runner_id}/tab")
async def dismiss_runner_tab(runner_id: str):
    """종료된 runner 탭 dismiss — RECENT_RUNNERS_KEY에서 제거 + per-runner 키 즉시 삭제"""
    success = await executor_service.dismiss_runner(runner_id)
    if not success:
        raise HTTPException(status_code=500, detail="dismiss 실패")
    return {"success": True, "runner_id": runner_id}


@router.get("/merge-queue", response_model=list[MergeQueueItem])
async def get_merge_queue():
    """Merge Queue 목록 조회"""
    return await executor_service.get_merge_queue()


@router.post("/merge-queue")
async def enqueue_merge(request: MergeQueueEnqueueRequest):
    """Merge Queue에 항목 직접 투입 (테스트/수동용, Admin 포트 전용)"""
    return await executor_service.enqueue_merge(
        request.branch, request.plan_file, request.project, request.worktree_path
    )


@router.get("/merge-history", response_model=list[MergeHistoryItem])
@router.get("/merge/history", response_model=list[MergeHistoryItem])
async def get_merge_history(limit: int = 50):
    """Merge 실행 이력 조회 (최신순, 기본 50건)"""
    return await executor_service.get_merge_history(limit=limit)


@router.get("/merge/{runner_id}", response_model=MergeStatusResponse)
async def get_merge_status(runner_id: str):
    """특정 runner의 merge 상태 조회"""
    status = await executor_service.get_merge_status(runner_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"merge status not found for runner {runner_id}")
    return status


@router.post("/merge/{runner_id}/retry")
async def retry_merge_request(runner_id: str, request: RetryMergeRequest = RetryMergeRequest()):
    """Merge 재시도 요청 — Redis 키 만료 시 payload로 재발급 가능"""
    return await executor_service.send_runner_command(runner_id, "retry-merge", extra=request.model_dump(exclude_none=True))


@router.post("/merge/{runner_id}/revert")
async def revert_merge_request(runner_id: str):
    """Merge 되돌리기 요청"""
    return await executor_service.send_runner_command(runner_id, "revert-merge")


@router.post("/merge/direct")
async def direct_merge(request: DirectMergeRequest):
    """직접 머지 — 러너 없이 branch/worktree만으로 머지 실행 (삭제된 러너 재시도용)"""
    return await executor_service.send_direct_merge_command(
        request.branch, request.worktree_path, request.plan_file
    )


__all__ = ['router']

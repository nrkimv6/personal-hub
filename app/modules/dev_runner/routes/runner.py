"""실행 제어 API"""

import asyncio
import json
from datetime import datetime
from typing import Optional
import redis
import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Query, Request

from app.modules.dev_runner.schemas import (
    DirectMergeRequest,
    DevRunnerReadinessResponse,
    MergeHistoryItem,
    MergeQueueItem,
    MergeStatusResponse,
    OrphanRunnerCandidate,
    ReattachRunnerRequest,
    ReattachRunnerResponse,
    RetryMergeRequest,
    RunRequest,
    RunStatusResponse,
    RunnerListItem,
    PlanStorageRootStatusItem,
    PlanStorageRootStatusResponse,
)
from app.modules.dev_runner.services.executor_service import executor_service
from app.modules.dev_runner.services.readiness_service import build_dev_runner_readiness
from app.modules.dev_runner.services.settings_service import settings_service

router = APIRouter()
READINESS_STORAGE_ROOT_TIMEOUT_SECONDS = 5


def _readiness_storage_roots_timeout_response() -> PlanStorageRootStatusResponse:
    checked_at = datetime.now().isoformat(timespec="seconds")
    return PlanStorageRootStatusResponse(
        checked_at=checked_at,
        roots=[
            PlanStorageRootStatusItem(
                project="plans",
                repo_root="",
                worktree_path="",
                exists=True,
                status="unknown",
                checked_at=checked_at,
                error=f"plan storage root status timed out after {READINESS_STORAGE_ROOT_TIMEOUT_SECONDS}s",
            )
        ],
        total=1,
    )


def _readiness_load_engine_config() -> tuple[dict | None, str | None]:
    from app.modules.dev_runner.routes.engines import get_engines_json_path

    try:
        engines_path = get_engines_json_path()
        if not engines_path.exists():
            return None, "engines.json file not found"
        payload = json.loads(engines_path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            return None, "engines.json payload is not an object"
        return payload, None
    except Exception as exc:
        return None, str(exc)


def _readiness_load_quota_snapshot() -> tuple[dict | None, str | None]:
    try:
        from app.shared.llm_registry import load_quota_state

        state = load_quota_state()
        if not state:
            return None, None
        return {
            key: {
                "weekly_used_pct": quota.weekly_used_pct,
                "short_cooldown_until": quota.short_cooldown_until.isoformat() if quota.short_cooldown_until else None,
            }
            for key, quota in state.items()
        }, None
    except Exception as exc:
        return None, str(exc)


@router.get("/runners", response_model=list[RunnerListItem])
async def list_runners(include_hidden: bool = Query(False, description="diagnostics only: include hidden/test runner rows")):
    """사용자-facing runner 목록 조회. 기본값은 visible runner만 반환한다."""
    try:
        return await executor_service.get_all_runners(include_hidden=include_hidden)
    except (redis.ConnectionError, aioredis.ConnectionError):
        raise HTTPException(status_code=503, detail="Redis 연결 실패")


@router.get("/runners/orphans", response_model=list[OrphanRunnerCandidate])
async def list_orphan_runners():
    """Redis 상태가 소실된 visible reattach 후보만 조회한다.

    오래된 log-only/test-trigger 후보는 diagnostics count 대상일 수 있지만
    이 사용자-facing endpoint의 runner 후보로 반환하지 않는다.
    """
    try:
        return await executor_service.discover_orphan_runners()
    except (redis.ConnectionError, aioredis.ConnectionError):
        raise HTTPException(status_code=503, detail="Redis 연결 실패")


@router.get("/runners/{runner_id}", response_model=RunStatusResponse)
async def get_runner_status(runner_id: str):
    """특정 runner 상태 조회 (session_id 포함)"""
    try:
        return await executor_service.get_runner_status(runner_id)
    except (redis.ConnectionError, aioredis.ConnectionError):
        raise HTTPException(status_code=503, detail="Redis 연결 실패")


@router.post("/runners/{runner_id}/stop")
async def stop_runner(runner_id: str):
    """특정 runner 중지"""
    return await executor_service.stop_dev_runner(runner_id)


@router.post("/stop/{runner_id}")
async def stop_runner_legacy(runner_id: str):
    """특정 runner 중지 (legacy path)."""
    return await executor_service.stop_dev_runner(runner_id)


@router.post("/run", response_model=RunStatusResponse)
async def start_run(request: RunRequest, http_request: Request):
    """plan-runner 실행 시작"""
    allow_test_repo_root = http_request.headers.get("x-api-gate-bypass") == "1"
    return await executor_service.start_dev_runner(
        request,
        allow_test_repo_root=allow_test_repo_root,
    )


@router.post("/stop-all")
async def stop_all_runners():
    """모든 active runner 일괄 중지"""
    return await executor_service.stop_all_runners()


@router.post("/stop")
async def stop_run():
    """plan-runner 실행 중지 (하위호환 — 첫 번째 active runner 종료)"""
    try:
        await executor_service.async_redis.ping()
    except Exception:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    try:
        runners = await executor_service.get_all_runners(visible_only=False, include_hidden=True)
    except (redis.ConnectionError, aioredis.ConnectionError):
        raise HTTPException(status_code=503, detail="Redis 연결 실패")
    if not runners:
        raise HTTPException(status_code=404, detail="Not running")
    return await executor_service.stop_dev_runner(runners[0].runner_id)


@router.get("/status", response_model=RunStatusResponse)
async def get_status():
    """실행 상태 조회 (하위호환 — 첫 번째 active runner)"""
    return await executor_service.get_process_status()


@router.get("/readiness", response_model=DevRunnerReadinessResponse)
async def get_readiness():
    """실행 시작 전 readiness 요약 조회 (읽기 전용)."""
    status = await executor_service.get_process_status()
    from app.modules.dev_runner.routes.plans import _collect_plan_storage_roots_status_sync
    try:
        storage_roots = await asyncio.wait_for(
            asyncio.to_thread(_collect_plan_storage_roots_status_sync),
            timeout=READINESS_STORAGE_ROOT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        storage_roots = _readiness_storage_roots_timeout_response()
    engine_config, engine_config_error = await asyncio.to_thread(_readiness_load_engine_config)
    quota_snapshot, quota_error = await asyncio.to_thread(_readiness_load_quota_snapshot)
    settings = await asyncio.to_thread(settings_service.get)
    return build_dev_runner_readiness(
        status,
        storage_roots,
        engine_config=engine_config,
        engine_config_error=engine_config_error,
        quota_snapshot=quota_snapshot,
        quota_error=quota_error,
        default_engine=settings.default_engine,
        default_fix_engine=settings.default_fix_engine,
    )


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


@router.get("/commands/{command_id}")
async def get_command_result(command_id: str):
    """Accepted runner command 결과를 command-specific result key에서 조회"""
    return await executor_service.get_command_result(command_id)


@router.post("/runners/{runner_id}/reattach", response_model=ReattachRunnerResponse)
async def reattach_runner(runner_id: str, request: ReattachRunnerRequest = ReattachRunnerRequest()):
    """Redis 상태 소실 runner를 사용자 승인으로 active 상태에 재연결"""
    return await executor_service.reattach_runner(runner_id, request)


@router.post("/runners/{runner_id}/orphans/kill")
async def kill_orphan_runner(runner_id: str):
    """Redis 상태 소실 runner 후보의 live PID를 evidence 재확인 후 종료"""
    return await executor_service.kill_orphan_runner(runner_id)


@router.post("/runners/{runner_id}/retry-merge")
async def retry_merge(runner_id: str, request: RetryMergeRequest = RetryMergeRequest()):
    """머지 충돌 후 재머지 시도 (service_lock 승인 플래그 포함)"""
    extra = request.model_dump(exclude_none=True)
    return await executor_service.send_runner_command(runner_id, "retry-merge", extra=extra)


@router.delete("/runners/{runner_id}/worktree")
async def cleanup_worktree(runner_id: str):
    """runner worktree 수동 정리"""
    return await executor_service.send_runner_command(runner_id, "cleanup-worktree")


@router.post("/runners/cleanup-stale")
async def cleanup_stale_runners():
    """plan 파일 없는 stale runner를 Redis에서 정리 (멱등, 여러 번 호출 안전)"""
    result = await executor_service.cleanup_stale_runners()
    cleaned_active = result.get("cleaned_active", 0)
    cleaned_recent = result.get("cleaned_recent", 0)
    preserved_recent = result.get("preserved_recent", 0)
    return {
        "success": True,
        "cleaned": result.get("total", cleaned_active + cleaned_recent),
        "cleaned_active": cleaned_active,
        "cleaned_recent": cleaned_recent,
        "preserved_recent": preserved_recent,
        "detail": {
            "cleaned_active": cleaned_active,
            "cleaned_recent": cleaned_recent,
            "preserved_recent": preserved_recent,
        },
    }


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


@router.get("/merge-queue-length")
async def get_merge_queue_length():
    """순수 대기 수 반환 (실행 중 runner 제외). 외부 소비자용 경량 엔드포인트."""
    length = await executor_service.get_merge_queue_length()
    return {"length": length}


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
        request.branch,
        request.worktree_path,
        request.plan_file,
        approve_service_lock=request.approve_service_lock,
    )


__all__ = ['router']

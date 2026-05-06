"""Worker status, stats, cleanup, and quota-pause routes."""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.services import provider_registry
from app.modules.claude_worker.services.execution_window_service import LLMExecutionWindowService
from app.modules.claude_worker.routes.llm_schemas import (
    HistoryStatsResponse,
    LLMStatsResponse,
    LLMWorkerStatusResponse,
)

router = APIRouter(tags=["llm"])

@router.get("/worker/status", response_model=LLMWorkerStatusResponse)
def get_worker_status(db: Session = Depends(get_db)):
    """워커 상태 조회."""
    service = LLMService(db)
    health = service.check_worker_health()
    return LLMWorkerStatusResponse(**health)


@router.get("/stats", response_model=LLMStatsResponse)
def get_stats(db: Session = Depends(get_db)):
    """통계 조회."""
    service = LLMService(db)
    stats = service.get_stats()
    return LLMStatsResponse(**stats)


@router.get("/history", response_model=HistoryStatsResponse)
def get_history_stats(
    start_date: Optional[date] = Query(None, description="시작일 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="종료일 (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
):
    """기간별 이력 통계."""
    service = LLMService(db)
    result = service.get_history_stats(start_date=start_date, end_date=end_date)
    return HistoryStatsResponse(**result)


@router.get("/stats/by-caller")
def get_caller_stats(db: Session = Depends(get_db)):
    """호출자별 통계."""
    service = LLMService(db)
    return service.get_caller_stats()


class RetryFailedCallersRequest(BaseModel):
    caller_type: Optional[str] = None


class ExecutionWindowPayload(BaseModel):
    start: str
    end: str
    days: Optional[list[int]] = None


class ExecutionWindowsPayload(BaseModel):
    timezone: str = "Asia/Seoul"
    allowed_windows: list[ExecutionWindowPayload] = []
    quiet_windows: list[ExecutionWindowPayload] = []


@router.post("/requests/batch/retry-failed-callers")
def retry_failed_callers_without_success(
    data: RetryFailedCallersRequest = None,
    db: Session = Depends(get_db),
):
    """성공한 적 없는 caller들의 실패 요청을 일괄 재시도.

    1번이라도 성공한 caller_id는 무시하고, 성공한 적 없는 caller의
    모든 실패 요청을 pending으로 재설정합니다.
    """
    service = LLMService(db)
    caller_type = data.caller_type if data else None
    return service.retry_failed_callers_without_success(caller_type=caller_type)


@router.get("/performance")
def get_performance_stats(
    hours: int = Query(24, ge=1, le=168, description="분석 기간 (시간, 최대 7일)"),
    db: Session = Depends(get_db),
):
    """성능 분석 통계.

    LLM 처리 시간 분석, 시간대별 분포, 느린 요청 목록을 제공합니다.
    """
    service = LLMService(db)
    return service.get_performance_stats(hours=hours)


# ========== Cleanup ==========

class CleanupResponse(BaseModel):
    stale_processing: int
    old_history: int


@router.post("/cleanup", response_model=CleanupResponse)
def run_cleanup(db: Session = Depends(get_db)):
    """Stale 요청 및 오래된 이력 정리.

    - stale_processing: 10분 이상 processing 상태인 요청을 failed로 변경
    - old_history: 7일 이상 된 completed/failed 요청 삭제
    """
    service = LLMService(db)
    result = service.run_cleanup()
    return CleanupResponse(**result)


@router.post("/cleanup/stale")
def cleanup_stale_processing(
    timeout_minutes: int = Query(10, ge=1, le=60, description="타임아웃 (분)"),
    db: Session = Depends(get_db),
):
    """Stale processing 요청만 정리."""
    service = LLMService(db)
    count = service.cleanup_stale_processing(timeout_minutes=timeout_minutes)
    return {"cleaned": count}


@router.post("/cleanup/history")
def cleanup_old_history(
    days: int = Query(7, ge=1, le=30, description="보관 기간 (일)"),
    hard_delete: bool = Query(True, description="물리 삭제 여부"),
    db: Session = Depends(get_db),
):
    """오래된 이력만 정리."""
    service = LLMService(db)
    count = service.cleanup_old_history(days=days, hard_delete=hard_delete)
    return {"deleted": count}


@router.get("/quota-status")
def get_quota_status(db: Session = Depends(get_db)):
    """provider별 quota pause 상태 조회.

    Returns:
        {"gemini": {"paused": true, "until": "...", "reason": "...", "remaining_seconds": N, "pending_blocked_count": M},
         "claude": {"paused": false, "pending_blocked_count": 0}}
    """
    service = LLMService(db)
    result = {}
    for provider in provider_registry.get_quota_providers():
        detail = service.get_provider_quota_pause_detail(provider)
        paused_until = detail.get("paused_until")
        blocked = service.get_blocked_pending_count(provider)
        if paused_until:
            remaining = int((paused_until - datetime.now()).total_seconds())
            result[provider] = {
                "paused": True,
                "until": paused_until.isoformat(),
                "reason": detail.get("reason"),
                "remaining_seconds": max(0, remaining),
                "pending_blocked_count": blocked,
            }
        else:
            result[provider] = {
                "paused": False,
                "pending_blocked_count": blocked,
            }
    window_decision = LLMExecutionWindowService().decide()
    if not window_decision.allowed:
        result["__execution_window"] = {
            "paused": True,
            "reason": window_decision.reason,
            "until": (
                window_decision.next_allowed_at.isoformat()
                if window_decision.next_allowed_at
                else None
            ),
            "remaining_seconds": (
                max(0, int((window_decision.next_allowed_at - datetime.now()).total_seconds()))
                if window_decision.next_allowed_at
                else None
            ),
            "pending_blocked_count": service.get_pending_count(),
            "timezone": window_decision.timezone,
        }
    else:
        result["__execution_window"] = {
            "paused": False,
            "pending_blocked_count": 0,
            "timezone": window_decision.timezone,
        }
    return result


@router.get("/execution-windows")
def get_execution_windows():
    """LLM worker execution window 설정 조회."""
    return LLMExecutionWindowService().load_config()


@router.put("/execution-windows")
def put_execution_windows(payload: ExecutionWindowsPayload):
    """LLM worker execution window 설정 저장."""
    try:
        return LLMExecutionWindowService().save_config(payload.dict())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/quota-pause/{provider}")
def clear_quota_pause(provider: str, db: Session = Depends(get_db)):
    """provider의 quota pause 수동 해제.

    pause 해제 후 quota 에러로 failed된 요청을 pending으로 재전환합니다.

    Returns:
        {"cleared": true, "reset_count": N}
    """
    service = LLMService(db)
    cleared = service.clear_provider_quota_pause(provider)
    reset_count = 0
    if cleared:
        reset_count = service.reset_quota_failed_requests(provider)
    return {"cleared": cleared, "reset_count": reset_count}

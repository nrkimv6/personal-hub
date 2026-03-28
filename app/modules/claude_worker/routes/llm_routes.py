"""Claude Worker API Routes."""

import asyncio
import json
import logging
from collections import deque
from datetime import date, datetime
from typing import AsyncGenerator, List, Optional

import redis.asyncio as aioredis

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.claude_worker.services.llm_service import LLMService

logger = logging.getLogger("claude_worker.api")

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])

# Redis 싱글톤 — SSE 스트리밍용 (매 요청 생성 방지)
_redis_async = aioredis.Redis(host="localhost", port=6379, decode_responses=True)


# ========== Schemas ==========

class LLMRequestCreate(BaseModel):
    caller_type: str
    caller_id: str
    prompt: str
    requested_by: str = "api"
    request_source: Optional[str] = None
    provider: str = "claude"
    model: str = ""
    queue_name: str = "utility"
    cli_options: Optional[dict] = None
    mode: str = "single"


class LLMRequestResponse(BaseModel):
    id: int
    caller_type: str
    caller_id: str
    status: str
    requested_by: Optional[str] = None
    request_source: Optional[str] = None
    provider: str = "claude"
    model: str = ""
    mode: str = "single"
    queue_name: str = "utility"
    requested_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    result: Optional[dict] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    prompt: Optional[str] = None
    cli_options: Optional[dict] = None

    class Config:
        from_attributes = True


class LLMRequestUpdate(BaseModel):
    cli_options: Optional[dict] = None
    prompt: Optional[str] = None


class LLMRequestDetailResponse(LLMRequestResponse):
    """상세 조회용 응답 (raw_response 포함)."""
    raw_response: Optional[str] = None


class LLMRequestListResponse(BaseModel):
    items: List[LLMRequestResponse]
    total: int
    page: int
    page_size: int
    pages: int


class LLMWorkerStatusResponse(BaseModel):
    status: str
    worker_id: Optional[str] = None
    state: Optional[str] = None
    processed_count: Optional[int] = None
    message: Optional[str] = None


class LLMStatsResponse(BaseModel):
    total: int
    pending: int
    processing: int
    completed: int
    failed: int


class BatchRetryRequest(BaseModel):
    request_ids: List[int]


class BatchDeleteRequest(BaseModel):
    request_ids: List[int]
    hard_delete: bool = False


class HistoryStatsResponse(BaseModel):
    data: List[dict]
    summary: dict


# ========== Endpoints ==========

def _to_response(request, include_raw: bool = False) -> LLMRequestResponse:
    """LLMRequest를 LLMRequestResponse로 변환.

    Args:
        request: LLMRequest 모델 인스턴스
        include_raw: True면 raw_response 포함 (상세 조회용)
    """
    result = None
    if request.result:
        try:
            result = json.loads(request.result)
        except json.JSONDecodeError:
            pass

    fields = dict(
        id=request.id,
        caller_type=request.caller_type,
        caller_id=request.caller_id,
        status=request.status,
        requested_by=request.requested_by,
        request_source=request.request_source,
        provider=getattr(request, "provider", "claude"),
        model=getattr(request, "model", ""),
        mode=getattr(request, "mode", "single"),
        queue_name=getattr(request, "queue_name", "utility"),
        requested_at=request.requested_at,
        processed_at=request.processed_at,
        result=result,
        error_message=request.error_message,
        retry_count=request.retry_count,
        prompt=request.prompt,
        cli_options=json.loads(request.cli_options) if request.cli_options else None,
    )

    if include_raw:
        fields["raw_response"] = getattr(request, "raw_response", None)
        return LLMRequestDetailResponse(**fields)

    return LLMRequestResponse(**fields)


@router.get("/queue-stats")
def get_queue_stats(db: Session = Depends(get_db)):
    """큐별 상태 통계 조회.

    Returns:
        {"system": {"pending": N, "processing": N, ...}, "utility": {...}}
    """
    service = LLMService(db)
    return service.get_queue_stats()


@router.get("/requests", response_model=LLMRequestListResponse)
def list_requests(
    status: Optional[str] = Query(None, description="상태 필터 (콤마로 구분하여 여러 상태 지정 가능, 예: completed,failed,cancelled)"),
    caller_type: Optional[str] = Query(None, description="호출자 타입 필터"),
    requested_by: Optional[str] = Query(None, description="요청자 필터"),
    include_deleted: bool = Query(False, description="삭제된 요청 포함"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(20, ge=1, le=100, description="페이지 크기"),
    queue_name: Optional[str] = Query(None, description="큐 이름 필터 (utility / system)"),
    db: Session = Depends(get_db),
):
    """요청 목록 조회."""
    service = LLMService(db)
    result = service.list_requests(
        status=status,
        caller_type=caller_type,
        requested_by=requested_by,
        include_deleted=include_deleted,
        page=page,
        page_size=page_size,
        queue_name=queue_name,
    )

    return LLMRequestListResponse(
        items=[_to_response(r) for r in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        pages=result["pages"],
    )


@router.post("/requests", response_model=LLMRequestResponse)
def create_request(
    data: LLMRequestCreate,
    db: Session = Depends(get_db),
):
    """LLM 요청 생성."""
    service = LLMService(db)
    request = service.enqueue(
        data.caller_type,
        data.caller_id,
        data.prompt,
        requested_by=data.requested_by,
        request_source=data.request_source,
        provider=data.provider,
        model=data.model,
        queue_name=data.queue_name,
        cli_options=data.cli_options,
        mode=data.mode,
    )
    return _to_response(request)


@router.get("/requests/grouped-by-caller")
def list_requests_grouped_by_caller(
    caller_type: Optional[str] = Query(None, description="호출자 타입 필터"),
    only_without_success: bool = Query(False, description="성공한 적 없는 caller만 조회"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(50, ge=1, le=100, description="페이지 크기"),
    db: Session = Depends(get_db),
):
    """caller_id별로 그룹화된 요청 목록 조회.

    각 caller별로 총 요청 수, 성공/실패 수, 성공 여부 등을 반환합니다.
    """
    service = LLMService(db)
    return service.list_requests_grouped_by_caller(
        caller_type=caller_type,
        only_without_success=only_without_success,
        page=page,
        page_size=page_size,
    )


@router.get("/requests/{request_id}", response_model=LLMRequestDetailResponse)
def get_request_by_id(
    request_id: int,
    db: Session = Depends(get_db),
):
    """단일 요청 조회 (ID로, raw_response 포함)."""
    service = LLMService(db)
    request = service.get_request_by_id(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    return _to_response(request, include_raw=True)


@router.patch("/requests/{request_id}", response_model=LLMRequestDetailResponse)
def update_request(
    request_id: int,
    data: LLMRequestUpdate,
    db: Session = Depends(get_db),
):
    """LLM 요청 수정 (pending/failed 상태만 허용)."""
    service = LLMService(db)
    request = service.get_request_by_id(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.status not in ("pending", "failed"):
        raise HTTPException(status_code=400, detail=f"Cannot update: status is {request.status}")
    updated = service.update_request(request_id, cli_options=data.cli_options, prompt=data.prompt)
    if not updated:
        raise HTTPException(status_code=400, detail="Update failed")
    return _to_response(updated, include_raw=True)


@router.get("/requests/by-caller/{caller_type}/{caller_id}", response_model=Optional[LLMRequestResponse])
def get_request_by_caller(
    caller_type: str,
    caller_id: str,
    db: Session = Depends(get_db),
):
    """요청 조회 (caller로)."""
    service = LLMService(db)
    request = service.get_result(caller_type, caller_id)
    if not request:
        return None
    return _to_response(request)


@router.post("/requests/{request_id}/retry")
def retry_request(
    request_id: int,
    db: Session = Depends(get_db),
):
    """실패한 요청 재시도."""
    service = LLMService(db)
    success = service.reset_to_pending(request_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot retry this request")
    return {"success": True, "message": "Request queued for retry"}


@router.post("/requests/{request_id}/cancel")
def cancel_request(
    request_id: int,
    db: Session = Depends(get_db),
):
    """pending 요청 취소."""
    service = LLMService(db)
    success = service.cancel_request(request_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot cancel this request (not pending)")
    return {"success": True, "message": "Request cancelled"}


@router.delete("/requests/{request_id}")
def delete_request(
    request_id: int,
    hard_delete: bool = Query(False, description="물리 삭제 여부"),
    db: Session = Depends(get_db),
):
    """요청 삭제."""
    service = LLMService(db)

    # 삭제 전에 요청 정보 조회 (instagram 후처리용)
    request = service.get_request_by_id(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")

    caller_type = request.caller_type
    caller_id = request.caller_id

    # 삭제 실행
    success = service.delete_request(request_id, hard_delete=hard_delete)
    if not success:
        raise HTTPException(status_code=404, detail="Request not found")

    return {"success": True, "message": "Request deleted"}


@router.post("/requests/batch/retry")
def batch_retry_requests(
    data: BatchRetryRequest,
    db: Session = Depends(get_db),
):
    """일괄 재시도."""
    service = LLMService(db)
    result = service.batch_retry(data.request_ids)
    return result


@router.post("/requests/batch/delete")
def batch_delete_requests(
    data: BatchDeleteRequest,
    db: Session = Depends(get_db),
):
    """일괄 삭제."""
    service = LLMService(db)
    result = service.batch_delete(data.request_ids, hard_delete=data.hard_delete)
    return result


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


# ========== Quota 관리 ==========

@router.get("/quota-status")
def get_quota_status(db: Session = Depends(get_db)):
    """provider별 quota pause 상태 조회.

    Returns:
        {"gemini": {"paused": true, "until": "...", "reason": "...", "remaining_seconds": N, "pending_blocked_count": M},
         "claude": {"paused": false, "pending_blocked_count": 0}}
    """
    service = LLMService(db)
    result = {}
    for provider in ["gemini", "claude"]:
        paused_until = service.get_provider_quota_pause(provider)
        blocked = service.get_blocked_pending_count(provider)
        if paused_until:
            remaining = int((paused_until - datetime.now()).total_seconds())
            result[provider] = {
                "paused": True,
                "until": paused_until.isoformat(),
                "remaining_seconds": max(0, remaining),
                "pending_blocked_count": blocked,
            }
        else:
            result[provider] = {
                "paused": False,
                "pending_blocked_count": blocked,
            }
    return result


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


# ========== Chat 스트리밍 엔드포인트 ==========

async def _chat_sse_generator(request_id: int) -> AsyncGenerator[str, None]:
    """Redis Pub/Sub 구독 -> SSE yield. __COMPLETED__ 수신 시 종료."""
    channel = f"llm-chat:stream:{request_id}"
    pubsub = _redis_async.pubsub()
    try:
        await pubsub.subscribe(channel)

        heartbeat_interval = 30  # seconds
        last_heartbeat = asyncio.get_event_loop().time()

        async for message in pubsub.listen():
            now = asyncio.get_event_loop().time()

            # heartbeat
            if now - last_heartbeat >= heartbeat_interval:
                yield ": heartbeat\n\n"
                last_heartbeat = now

            if message["type"] != "message":
                continue

            data = message["data"]
            if data == "__COMPLETED__":
                yield "event: completed\ndata: done\n\n"
                break
            else:
                escaped = data.replace("\n", "\\n")
                yield f"data: {escaped}\n\n"
    except Exception as e:
        logger.error(f"SSE stream error request_id={request_id}: {e}")
        yield f"data: [ERROR] {e}\n\n"
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception:
            pass


@router.get("/chat/{request_id}/stream")
async def stream_chat_logs(request_id: int, db: Session = Depends(get_db)):
    """chat 모드 요청의 실시간 SSE 스트림.

    Redis Pub/Sub llm-chat:stream:{request_id} 구독 후 SSE로 전달.
    __COMPLETED__ 수신 시 'event: completed' 발행 후 종료.
    """
    # 요청 존재 확인
    from app.modules.claude_worker.models.llm_request import LLMRequest
    req = db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="LLMRequest not found")

    return StreamingResponse(
        _chat_sse_generator(request_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/chat/{request_id}/logs")
def get_chat_logs(
    request_id: int,
    lines: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """chat 요청의 로그 파일 내용 반환 (fallback).

    stream_log_path가 있으면 파일 마지막 N줄 반환.
    없으면 raw_response 반환 (완료된 경우).
    """
    from app.modules.claude_worker.models.llm_request import LLMRequest
    req = db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="LLMRequest not found")

    if req.stream_log_path:
        import os
        if os.path.exists(req.stream_log_path):
            tail = deque(maxlen=lines)
            with open(req.stream_log_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    tail.append(line.rstrip("\n"))
            return {"source": "log_file", "lines": list(tail), "status": req.status}

    # fallback: raw_response
    return {
        "source": "raw_response",
        "lines": (req.raw_response or "").splitlines()[-lines:],
        "status": req.status,
    }

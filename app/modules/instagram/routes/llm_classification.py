"""Instagram LLM Classification API Routes.

claude_worker 모듈을 사용하는 Instagram 전용 LLM 분류 API.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.claude_worker.models.llm_request import LLMRequest, LLMWorkerStatus
from app.modules.instagram.services.llm_classifier_service import LLMClassifierService

logger = logging.getLogger("instagram.llm_api")

router = APIRouter(prefix="/api/v1/instagram/llm", tags=["instagram-llm"])

CALLER_TYPE = "instagram"


# ========== Schemas ==========

class LLMEventPeriodSchema(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None


class LLMLocationSchema(BaseModel):
    venue_name: Optional[str] = None
    address: Optional[str] = None


class LLMResultSchema(BaseModel):
    tag: Optional[str] = None  # 이벤트|팝업|홍보대사|리그램|후기|기타
    organizer: Optional[str] = None
    summary: Optional[str] = None
    prizes: Optional[list[str]] = None
    winner_count: Optional[int] = None
    purchase_required: Optional[str] = None  # 예_전부|예_부분|아니오
    event_period: Optional[LLMEventPeriodSchema] = None
    announcement_date: Optional[str] = None
    urls: Optional[list[str]] = None
    location: Optional[LLMLocationSchema] = None


class LLMRequestSchema(BaseModel):
    id: int
    post_id: int
    status: str
    requested_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    result: Optional[LLMResultSchema] = None
    error_message: Optional[str] = None
    retry_count: int = 0


class LLMRequestListResponse(BaseModel):
    requests: list[LLMRequestSchema]
    total: int
    page: int
    limit: int


class LLMRequestCreateSchema(BaseModel):
    post_ids: list[int]


class LLMWorkerStatusSchema(BaseModel):
    worker_id: str
    pid: Optional[int] = None
    started_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    current_state: str
    is_alive: bool
    processed_count: int = 0
    error_count: int = 0
    uptime_seconds: Optional[int] = None
    heartbeat_age_seconds: Optional[int] = None


class LLMWorkerHealthSchema(BaseModel):
    status: str  # healthy | warning | unhealthy | no_worker
    message: Optional[str] = None
    worker_id: Optional[str] = None
    state: Optional[str] = None
    processed_count: Optional[int] = None
    seconds_since_heartbeat: Optional[int] = None


class LLMStatsSchema(BaseModel):
    total: int
    pending: int
    processing: int
    completed: int
    failed: int


# ========== Helper Functions ==========

def _request_to_schema(request: LLMRequest) -> LLMRequestSchema:
    """LLMRequest를 스키마로 변환."""
    result = None
    if request.result:
        try:
            result_dict = json.loads(request.result)
            result = LLMResultSchema(**result_dict)
        except (json.JSONDecodeError, TypeError):
            pass

    # caller_id에서 post_id 추출
    post_id = int(request.caller_id) if request.caller_id.isdigit() else 0

    return LLMRequestSchema(
        id=request.id,
        post_id=post_id,
        status=request.status,
        requested_at=request.requested_at,
        processed_at=request.processed_at,
        result=result,
        error_message=request.error_message,
        retry_count=request.retry_count,
    )


# ========== Endpoints ==========

@router.get("/requests", response_model=LLMRequestListResponse)
async def get_llm_requests(
    status: Optional[str] = Query(None, description="상태 필터 (pending, processing, completed, failed)"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """LLM 분류 요청 목록 조회 (Instagram 관련만)."""
    query = db.query(LLMRequest).filter(LLMRequest.caller_type == CALLER_TYPE)

    if status:
        query = query.filter(LLMRequest.status == status)

    total = query.count()

    requests = (
        query.order_by(LLMRequest.requested_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return LLMRequestListResponse(
        requests=[_request_to_schema(r) for r in requests],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/requests/{request_id}", response_model=LLMRequestSchema)
async def get_llm_request(
    request_id: int,
    db: Session = Depends(get_db),
):
    """LLM 분류 요청 상세 조회."""
    request = db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
    if not request or request.caller_type != CALLER_TYPE:
        raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다")

    return _request_to_schema(request)


@router.get("/posts/{post_id}", response_model=Optional[LLMRequestSchema])
async def get_llm_result_by_post(
    post_id: int,
    db: Session = Depends(get_db),
):
    """게시물의 최신 LLM 분석 결과 조회.

    해당 게시물에 대한 가장 최근 LLM 분류 요청과 결과를 반환합니다.
    분류 요청이 없는 경우 null을 반환합니다.
    """
    request = (
        db.query(LLMRequest)
        .filter(
            LLMRequest.caller_type == CALLER_TYPE,
            LLMRequest.caller_id == str(post_id),
        )
        .order_by(LLMRequest.requested_at.desc())
        .first()
    )

    if not request:
        return None

    return _request_to_schema(request)


@router.post("/requests")
async def create_llm_requests(
    data: LLMRequestCreateSchema,
    db: Session = Depends(get_db),
):
    """수동 LLM 분류 요청 생성."""
    service = LLMClassifierService(db)

    created = []
    for post_id in data.post_ids:
        request = service.create_request(
            post_id=post_id,
            trigger_tag="manual",
            requested_by="manual",
        )
        if request:
            created.append(request.id)

    return {
        "success": True,
        "created_count": len(created),
        "request_ids": created,
    }


@router.post("/requests/{request_id}/retry")
async def retry_llm_request(
    request_id: int,
    db: Session = Depends(get_db),
):
    """완료되었거나 실패한 요청 재시도."""
    service = LLMClassifierService(db)

    success = service.reset_to_pending(request_id)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="재시도할 수 없는 상태입니다 (completed 또는 failed 상태만 재시도 가능)",
        )

    return {"success": True, "message": "요청이 재시도 대기열에 추가되었습니다"}


@router.get("/worker/status", response_model=LLMWorkerStatusSchema)
async def get_llm_worker_status(
    db: Session = Depends(get_db),
):
    """LLM 워커 상태 조회."""
    service = LLMClassifierService(db)
    worker = service.get_worker_status()

    if not worker:
        raise HTTPException(status_code=404, detail="활성 워커가 없습니다")

    now = datetime.now()
    return LLMWorkerStatusSchema(
        worker_id=worker.worker_id,
        pid=worker.pid,
        started_at=worker.started_at,
        last_heartbeat=worker.last_heartbeat,
        current_state=worker.current_state,
        is_alive=worker.is_alive,
        processed_count=worker.processed_count,
        error_count=worker.error_count,
        uptime_seconds=int((now - worker.started_at).total_seconds()) if worker.started_at else None,
        heartbeat_age_seconds=int((now - worker.last_heartbeat).total_seconds()) if worker.last_heartbeat else None,
    )


@router.get("/worker/health", response_model=LLMWorkerHealthSchema)
async def get_llm_worker_health(
    db: Session = Depends(get_db),
):
    """LLM 워커 헬스체크."""
    service = LLMClassifierService(db)
    health = service.check_worker_health()

    return LLMWorkerHealthSchema(**health)


@router.get("/stats", response_model=LLMStatsSchema)
async def get_llm_stats(
    db: Session = Depends(get_db),
):
    """LLM 분류 통계 조회 (Instagram 관련만)."""
    service = LLMClassifierService(db)
    stats = service.get_stats()

    return LLMStatsSchema(**stats)

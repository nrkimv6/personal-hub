"""Instagram LLM Classification API Routes."""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.instagram_llm_request import InstagramLLMClassificationRequest
from app.modules.instagram.models.schemas import (
    LLMRequestCreateSchema,
    LLMRequestListResponse,
    LLMRequestSchema,
    LLMResultSchema,
    LLMStatsSchema,
    LLMWorkerHealthSchema,
    LLMWorkerStatusSchema,
)
from app.modules.instagram.services.llm_classifier_service import LLMClassifierService

logger = logging.getLogger("instagram.llm_api")

router = APIRouter(prefix="/api/v1/instagram/llm", tags=["instagram-llm"])


def _request_to_schema(request: InstagramLLMClassificationRequest) -> LLMRequestSchema:
    """DB 모델을 스키마로 변환."""
    llm_result = None
    if request.llm_result:
        try:
            result_dict = json.loads(request.llm_result)
            llm_result = LLMResultSchema(**result_dict)
        except (json.JSONDecodeError, TypeError):
            pass

    return LLMRequestSchema(
        id=request.id,
        post_id=request.post_id,
        requested_at=request.requested_at,
        requested_by=request.requested_by,
        trigger_tag=request.trigger_tag,
        status=request.status,
        processed_at=request.processed_at,
        llm_result=llm_result,
        confidence_score=request.confidence_score,
        error_message=request.error_message,
        retry_count=request.retry_count,
    )


@router.get("/requests", response_model=LLMRequestListResponse)
async def get_llm_requests(
    status: Optional[str] = Query(None, description="상태 필터 (pending, processing, completed, failed)"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """LLM 분류 요청 목록 조회."""
    query = db.query(InstagramLLMClassificationRequest)

    if status:
        query = query.filter(InstagramLLMClassificationRequest.status == status)

    total = query.count()

    requests = (
        query.order_by(InstagramLLMClassificationRequest.requested_at.desc())
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
    request = db.query(InstagramLLMClassificationRequest).get(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다")

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
    """실패한 요청 재시도."""
    service = LLMClassifierService(db)

    success = service.reset_to_pending(request_id)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="재시도할 수 없는 상태입니다 (failed 상태만 재시도 가능)",
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
        current_request_id=worker.current_request_id,
        is_alive=worker.is_alive,
        processed_count=worker.processed_count,
        error_count=worker.error_count,
        uptime_seconds=int((now - worker.started_at).total_seconds()),
        heartbeat_age_seconds=int((now - worker.last_heartbeat).total_seconds()),
    )


@router.get("/worker/health", response_model=LLMWorkerHealthSchema)
async def get_llm_worker_health(
    db: Session = Depends(get_db),
):
    """LLM 워커 헬스체크."""
    service = LLMClassifierService(db)
    health = service.check_worker_health()

    return LLMWorkerHealthSchema(
        status=health["status"],
        message=health["message"],
        worker=health.get("worker"),
    )


@router.get("/stats", response_model=LLMStatsSchema)
async def get_llm_stats(
    db: Session = Depends(get_db),
):
    """LLM 분류 통계 조회."""
    service = LLMClassifierService(db)
    stats = service.get_stats()

    return LLMStatsSchema(**stats)

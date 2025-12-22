"""Claude Worker API Routes."""

import json
import logging
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.claude_worker.services.llm_service import LLMService

logger = logging.getLogger("claude_worker.api")

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])


# ========== Schemas ==========

class LLMRequestCreate(BaseModel):
    caller_type: str
    caller_id: str
    prompt: str
    requested_by: str = "api"
    request_source: Optional[str] = None


class LLMRequestResponse(BaseModel):
    id: int
    caller_type: str
    caller_id: str
    status: str
    requested_by: Optional[str] = None
    request_source: Optional[str] = None
    requested_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    result: Optional[dict] = None
    error_message: Optional[str] = None
    retry_count: int = 0

    class Config:
        from_attributes = True


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

@router.post("/requests", response_model=LLMRequestResponse)
def create_request(
    data: LLMRequestCreate,
    db: Session = Depends(get_db),
):
    """LLM 요청 생성."""
    service = LLMService(db)
    request = service.enqueue(data.caller_type, data.caller_id, data.prompt)
    return LLMRequestResponse(
        id=request.id,
        caller_type=request.caller_type,
        caller_id=request.caller_id,
        status=request.status,
    )


@router.get("/requests/{caller_type}/{caller_id}", response_model=Optional[LLMRequestResponse])
def get_request(
    caller_type: str,
    caller_id: str,
    db: Session = Depends(get_db),
):
    """LLM 요청 조회."""
    service = LLMService(db)
    request = service.get_result(caller_type, caller_id)
    if not request:
        return None

    result = None
    if request.result:
        import json
        try:
            result = json.loads(request.result)
        except json.JSONDecodeError:
            pass

    return LLMRequestResponse(
        id=request.id,
        caller_type=request.caller_type,
        caller_id=request.caller_id,
        status=request.status,
        result=result,
        error_message=request.error_message,
    )


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

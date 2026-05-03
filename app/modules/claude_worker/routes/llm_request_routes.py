"""LLM request CRUD and batch routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.routes.llm_schemas import (
    BatchDeleteRequest,
    BatchRetryRequest,
    LLMBootstrapResponse,
    LLMRequestCreate,
    LLMRequestDetailResponse,
    LLMRequestListResponse,
    LLMRequestResponse,
    LLMRequestUpdate,
    LLMStatsResponse,
    LLMWorkerStatusResponse,
    _to_response,
)

router = APIRouter(tags=["llm"])

@router.get("/queue-stats")
def get_queue_stats(db: Session = Depends(get_db)):
    """큐별 상태 통계 조회.

    Returns:
        {"system": {"pending": N, "processing": N, ...}, "utility": {...}}
    """
    service = LLMService(db)
    return service.get_queue_stats()


@router.get("/bootstrap", response_model=LLMBootstrapResponse)
def get_llm_bootstrap(
    status: Optional[str] = Query(None, description="상태 필터 (콤마로 구분하여 여러 상태 지정 가능, 예: completed,failed,cancelled)"),
    caller_type: Optional[str] = Query(None, description="호출자 타입 필터"),
    requested_by: Optional[str] = Query(None, description="요청자 필터"),
    include_deleted: bool = Query(False, description="삭제된 요청 포함"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(20, ge=1, le=100, description="페이지 크기"),
    queue_name: Optional[str] = Query(None, description="큐 이름 필터 (utility / system)"),
    db: Session = Depends(get_db),
):
    """LLM /llm 초기 진입용 묶음 응답."""
    service = LLMService(db)
    result = service.get_bootstrap_data(
        status=status,
        caller_type=caller_type,
        requested_by=requested_by,
        include_deleted=include_deleted,
        page=page,
        page_size=page_size,
        queue_name=queue_name,
    )
    request_list = result["list"]
    return LLMBootstrapResponse(
        list=LLMRequestListResponse(
            items=[_to_response(item) for item in request_list["items"]],
            total=request_list["total"],
            page=request_list["page"],
            page_size=request_list["page_size"],
            pages=request_list["pages"],
        ),
        stats=LLMStatsResponse(**result["stats"]),
        queue_stats=result["queue_stats"],
        worker_status=LLMWorkerStatusResponse(**result["worker_status"]),
    )


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

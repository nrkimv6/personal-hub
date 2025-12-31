"""Writing API Routes - 글 생성 관리 API."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.writing.services.writing_service import WritingService

router = APIRouter(prefix="/api/writing", tags=["writing"])


# ========== Pydantic 스키마 ==========


class WritingUpdateRequest(BaseModel):
    """글 수정 요청."""

    content: Optional[str] = None


class RatingRequest(BaseModel):
    """평가 요청."""

    rating: Optional[int] = None  # 1: 추천, -1: 비추천, None: 취소


class SourceCreateRequest(BaseModel):
    """소스 생성 요청."""

    content: str
    category: Optional[str] = None
    source_info: Optional[str] = None


class BulkSourceRequest(BaseModel):
    """소스 일괄 생성 요청."""

    sources: list[dict]


# ========== 생성된 글 조회 ==========


@router.get("/generated")
def list_generated_writings(
    task_type: Optional[str] = None,
    rating: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """생성된 글 목록 조회."""
    service = WritingService(db)

    # rating 파라미터 파싱
    rating_value = None
    if rating is not None:
        if rating == "null":
            rating_value = 0  # 미평가
        elif rating in ("1", "-1"):
            rating_value = int(rating)

    result = service.list_generated_writings(
        task_type=task_type,
        rating=rating_value,
        page=page,
        page_size=page_size,
    )

    return {
        "items": [_writing_to_dict(w) for w in result["items"]],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
        "pages": result["pages"],
    }


@router.get("/generated/{writing_id}")
def get_generated_writing(
    writing_id: int,
    db: Session = Depends(get_db),
):
    """생성된 글 상세 조회."""
    service = WritingService(db)
    writing = service.get_generated_writing(writing_id)
    if not writing:
        raise HTTPException(404, "Writing not found")
    return _writing_to_dict(writing, include_full=True)


# ========== 글 관리 ==========


@router.put("/generated/{writing_id}")
def update_generated_writing(
    writing_id: int,
    data: WritingUpdateRequest,
    db: Session = Depends(get_db),
):
    """생성된 글 수정."""
    service = WritingService(db)
    writing = service.update_generated_writing(
        writing_id=writing_id,
        content=data.content,
    )
    if not writing:
        raise HTTPException(404, "Writing not found")
    return _writing_to_dict(writing, include_full=True)


@router.delete("/generated/{writing_id}")
def delete_generated_writing(
    writing_id: int,
    hard: bool = False,
    db: Session = Depends(get_db),
):
    """생성된 글 삭제 (기본: soft delete)."""
    service = WritingService(db)
    success = service.delete_generated_writing(writing_id, hard_delete=hard)
    if not success:
        raise HTTPException(404, "Writing not found")
    return {"deleted": True}


@router.post("/generated/{writing_id}/rate")
def rate_generated_writing(
    writing_id: int,
    data: RatingRequest,
    db: Session = Depends(get_db),
):
    """생성된 글 평가 (추천/비추천)."""
    if data.rating is not None and data.rating not in (1, -1):
        raise HTTPException(400, "rating must be 1, -1, or null")

    service = WritingService(db)
    writing = service.rate_generated_writing(writing_id, data.rating)
    if not writing:
        raise HTTPException(404, "Writing not found")

    return {"id": writing_id, "rating": data.rating}


# ========== 소스 관리 ==========


@router.get("/sources")
def list_sources(
    category: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """글 소스 목록 조회."""
    service = WritingService(db)
    result = service.list_sources(
        category=category,
        page=page,
        page_size=page_size,
    )

    return {
        "items": [
            {
                "id": s.id,
                "category": s.category,
                "source_info": s.source_info,
                "preview": s.content[:100] if s.content else "",
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in result["items"]
        ],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
        "pages": result["pages"],
    }


@router.get("/sources/{source_id}")
def get_source(
    source_id: int,
    db: Session = Depends(get_db),
):
    """글 소스 상세 조회."""
    from app.models.writing import WritingSource

    source = db.query(WritingSource).filter(WritingSource.id == source_id).first()
    if not source:
        raise HTTPException(404, "Source not found")

    return {
        "id": source.id,
        "content": source.content,
        "category": source.category,
        "source_info": source.source_info,
        "created_at": source.created_at.isoformat() if source.created_at else None,
    }


@router.post("/sources")
def add_source(
    data: SourceCreateRequest,
    db: Session = Depends(get_db),
):
    """글 소스 추가."""
    service = WritingService(db)
    source = service.add_source(
        content=data.content,
        category=data.category,
        source_info=data.source_info,
    )
    return {
        "id": source.id,
        "category": source.category,
        "created_at": source.created_at.isoformat() if source.created_at else None,
    }


@router.post("/sources/bulk")
def bulk_add_sources(
    data: BulkSourceRequest,
    db: Session = Depends(get_db),
):
    """소스 일괄 추가."""
    service = WritingService(db)
    added = service.bulk_add_sources(data.sources)
    return {"added": added}


@router.delete("/sources/{source_id}")
def delete_source(
    source_id: int,
    db: Session = Depends(get_db),
):
    """글 소스 삭제."""
    service = WritingService(db)
    success = service.delete_source(source_id)
    if not success:
        raise HTTPException(404, "Source not found")
    return {"deleted": True}


# ========== 통계 ==========


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """통계 조회."""
    service = WritingService(db)
    return service.get_stats()


# ========== 실행 ==========


@router.post("/run")
def run_writing_task(db: Session = Depends(get_db)):
    """작문 태스크 수동 실행."""
    service = WritingService(db)
    try:
        result = service.run_writing_task()
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


# ========== 헬퍼 함수 ==========


def _writing_to_dict(writing, include_full: bool = False) -> dict:
    """GeneratedWriting을 dict로 변환."""
    result = {
        "id": writing.id,
        "task_type": writing.task_type,
        "source_ids": writing.get_source_id_list(),
        "rating": writing.rating,
        "created_at": writing.created_at.isoformat() if writing.created_at else None,
        "preview": writing.content[:200] if writing.content else "",
    }

    if include_full:
        result["content"] = writing.content
        result["raw_response"] = writing.raw_response
        result["prompt_used"] = writing.prompt_used
        result["schedule_run_id"] = writing.schedule_run_id
        result["updated_at"] = (
            writing.updated_at.isoformat() if writing.updated_at else None
        )

    return result

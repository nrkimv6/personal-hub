"""
미분류 게시물 API 라우트 - 재분류 지원
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.uncategorized_service import uncategorized_service
from app.schemas.uncategorized import (
    UncategorizedResponse,
    UncategorizedList,
    ReclassifyRequest,
    ReclassifyResponse,
)

router = APIRouter(prefix="/api/v1/uncategorized", tags=["uncategorized"])


@router.get("", response_model=UncategorizedList)
def get_uncategorized_list(
    original_tag: Optional[str] = Query(None, description="원본 태그 (홍보대사/기타)"),
    include_reclassified: bool = Query(False, description="재분류된 항목 포함 여부"),
    sort_by: str = Query("created_at", description="정렬 기준"),
    sort_order: str = Query("desc", description="정렬 순서 (asc/desc)"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(50, ge=1, le=200, description="페이지 크기"),
    db: Session = Depends(get_db),
):
    """
    미분류 게시물 목록을 조회합니다.

    - 기본적으로 재분류되지 않은 항목만 표시
    - 원본 태그(홍보대사/기타)로 필터링 가능
    """
    return uncategorized_service.get_uncategorized_list(
        db=db,
        original_tag=original_tag,
        include_reclassified=include_reclassified,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )


@router.get("/{uncategorized_id}", response_model=UncategorizedResponse)
def get_uncategorized(uncategorized_id: int, db: Session = Depends(get_db)):
    """
    미분류 항목 상세 조회
    """
    item = uncategorized_service.get_uncategorized(db, uncategorized_id)
    if not item:
        raise HTTPException(status_code=404, detail="Uncategorized post not found")
    return item


@router.post("/{uncategorized_id}/reclassify", response_model=ReclassifyResponse)
def reclassify(
    uncategorized_id: int,
    data: ReclassifyRequest,
    db: Session = Depends(get_db),
):
    """
    미분류 항목을 Event 또는 Popup으로 재분류합니다.

    - target: "event" 또는 "popup"
    - 재분류 시 해당 테이블에 새 레코드 생성
    - InstagramPost의 classified_type/id도 업데이트
    """
    result = uncategorized_service.reclassify(db, uncategorized_id, data)
    if not result:
        raise HTTPException(status_code=404, detail="Uncategorized post not found")
    return result


@router.delete("/{uncategorized_id}", status_code=204)
def delete_uncategorized(uncategorized_id: int, db: Session = Depends(get_db)):
    """
    미분류 항목을 삭제합니다.
    """
    success = uncategorized_service.delete_uncategorized(db, uncategorized_id)
    if not success:
        raise HTTPException(status_code=404, detail="Uncategorized post not found")
    return None

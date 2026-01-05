"""Activity Centers API Routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.activity.models.schemas import (
    CenterCreate,
    CenterUpdate,
    CenterResponse,
    CenterListResponse,
)
from app.modules.activity.services.center_service import CenterService

router = APIRouter(prefix="/centers", tags=["activity-centers"])


@router.get("", response_model=CenterListResponse)
def list_centers(
    region_sido: Optional[str] = Query(None, description="시/도"),
    region_sigungu: Optional[str] = Query(None, description="시/군/구"),
    center_type: Optional[str] = Query(None, description="센터 타입"),
    is_active: Optional[bool] = Query(None, description="활성 상태"),
    keyword: Optional[str] = Query(None, description="검색어"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """센터 목록 조회."""
    service = CenterService(db)
    centers, total = service.get_list(
        region_sido=region_sido,
        region_sigungu=region_sigungu,
        center_type=center_type,
        is_active=is_active,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )

    return CenterListResponse(
        items=[service.to_response(c, include_count=True) for c in centers],
        total=total,
    )


@router.get("/{center_id}", response_model=CenterResponse)
def get_center(
    center_id: int,
    db: Session = Depends(get_db),
):
    """센터 상세 조회."""
    service = CenterService(db)
    center = service.get_by_id(center_id)

    if not center:
        raise HTTPException(status_code=404, detail="센터를 찾을 수 없습니다.")

    return service.to_response(center, include_count=True)


@router.post("", response_model=CenterResponse, status_code=201)
def create_center(
    data: CenterCreate,
    db: Session = Depends(get_db),
):
    """센터 생성."""
    service = CenterService(db)
    center = service.create(data)
    return service.to_response(center)


@router.put("/{center_id}", response_model=CenterResponse)
def update_center(
    center_id: int,
    data: CenterUpdate,
    db: Session = Depends(get_db),
):
    """센터 수정."""
    service = CenterService(db)
    center = service.update(center_id, data)

    if not center:
        raise HTTPException(status_code=404, detail="센터를 찾을 수 없습니다.")

    return service.to_response(center, include_count=True)


@router.delete("/{center_id}", status_code=204)
def delete_center(
    center_id: int,
    db: Session = Depends(get_db),
):
    """센터 삭제."""
    service = CenterService(db)
    success = service.delete(center_id)

    if not success:
        raise HTTPException(status_code=404, detail="센터를 찾을 수 없습니다.")

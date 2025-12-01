"""
Business 라우트 - 업체 API
설계 문서: 2025-12-01_monitoring_restructure_design.md
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.business import (
    Business,
    BusinessCreate,
    BusinessUpdate,
    BusinessWithItems,
)
from app.schemas.biz_item import BizItem
from app.services.business_service import business_service
from app.services.biz_item_service import biz_item_service

router = APIRouter(prefix="/api/v1/businesses", tags=["businesses"])


@router.get("/", response_model=List[Business])
def get_businesses(db: Session = Depends(get_db)):
    """전체 업체 목록 조회"""
    return business_service.get_all(db)


@router.post("/", response_model=Business, status_code=201)
def create_business(data: BusinessCreate, db: Session = Depends(get_db)):
    """업체 생성"""
    # 중복 체크
    existing = business_service.get_by_business_id(db, data.business_id)
    if existing:
        raise HTTPException(status_code=400, detail=f"Business with business_id '{data.business_id}' already exists")

    return business_service.create(db, data)


@router.get("/{business_id}", response_model=BusinessWithItems)
def get_business(business_id: int, db: Session = Depends(get_db)):
    """업체 상세 조회 (아이템 포함)"""
    business = business_service.get_by_id(db, business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


@router.put("/{business_id}", response_model=Business)
def update_business(business_id: int, data: BusinessUpdate, db: Session = Depends(get_db)):
    """업체 수정"""
    business = business_service.update(db, business_id, data)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


@router.delete("/{business_id}", status_code=204)
def delete_business(business_id: int, db: Session = Depends(get_db)):
    """업체 삭제 (하위 아이템/일정 모두 삭제)"""
    success = business_service.delete(db, business_id)
    if not success:
        raise HTTPException(status_code=404, detail="Business not found")
    return None


@router.get("/{business_id}/items", response_model=List[BizItem])
def get_business_items(business_id: int, db: Session = Depends(get_db)):
    """업체의 아이템 목록 조회"""
    business = business_service.get_by_id(db, business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    return biz_item_service.get_by_business(db, business_id)

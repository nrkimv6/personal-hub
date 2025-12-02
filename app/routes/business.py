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
    UrlImportRequest,
    UrlImportResponse,
)
from app.schemas.biz_item import BizItem, BizItemCreate
from app.schemas.monitor_schedule import MonitorScheduleCreate
from app.services.business_service import business_service
from app.services.biz_item_service import biz_item_service
from app.services.schedule_service import schedule_service
from app.utils.parsers import parse_naver_booking_url, extract_date_only

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


@router.post("/import-url", response_model=UrlImportResponse)
def import_from_url(data: UrlImportRequest, db: Session = Depends(get_db)):
    """
    URL에서 업체/아이템/일정을 자동 생성합니다.

    URL 형식: /booking/{category}/bizes/{businessId}/items/{itemId}?startDateTime=...

    - 업체가 없으면 자동 생성
    - 아이템이 없으면 자동 생성
    - 날짜가 URL에 있으면 일정도 자동 생성
    """
    # URL 파싱
    parsed = parse_naver_booking_url(data.url)

    if not parsed.is_valid:
        return UrlImportResponse(
            success=False,
            message=f"URL 파싱 실패: {parsed.error}",
            parsed_info={"url": data.url}
        )

    # 1. 업체 조회 또는 생성
    business = business_service.get_by_business_id(db, parsed.business_id)
    if not business:
        business_name = data.business_name or f"Business_{parsed.business_id}"
        business_type_id = int(parsed.business_type_id) if parsed.business_type_id else None

        business_data = BusinessCreate(
            business_id=parsed.business_id,
            business_type_id=business_type_id,
            name=business_name,
            service_type="naver",
            category=parsed.category,
            is_enabled=True
        )
        business = business_service.create(db, business_data)

    # 2. 아이템 조회 또는 생성
    item = biz_item_service.get_by_biz_item_id(db, business.id, parsed.item_id)
    if not item:
        item_data = BizItemCreate(
            business_id=business.id,
            biz_item_id=parsed.item_id,
            name=data.item_name,
            is_enabled=True,
            time_range=data.time_range,
            auto_booking_enabled=data.auto_booking_enabled,
            max_bookings_per_schedule=data.max_bookings_per_schedule
        )
        item = biz_item_service.create(db, item_data)

    # 3. 일정 생성 (날짜가 있는 경우)
    schedule_id = None
    date_str = extract_date_only(parsed.start_date)
    if date_str:
        # 이미 존재하는 일정인지 확인
        existing = schedule_service.get_by_date(db, item.id, date_str)
        if not existing:
            schedule_data = MonitorScheduleCreate(
                biz_item_id=item.id,
                date=date_str,
                is_enabled=True
            )
            schedule = schedule_service.create(db, schedule_data)
            schedule_id = schedule.id
        else:
            schedule_id = existing.id

    return UrlImportResponse(
        success=True,
        message="성공적으로 임포트되었습니다.",
        business_id=business.id,
        item_id=item.id,
        schedule_id=schedule_id,
        parsed_info={
            "category": parsed.category,
            "naver_business_id": parsed.business_id,
            "naver_item_id": parsed.item_id,
            "date": date_str,
            "business_type_id": parsed.business_type_id
        }
    )

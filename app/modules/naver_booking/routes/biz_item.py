"""
BizItem 라우트 - 아이템 API
설계 문서: 2025-12-01_monitoring_restructure_design.md
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.biz_item import (
    BizItem,
    BizItemCreate,
    BizItemUpdate,
    BizItemWithSchedules,
)
from app.schemas.monitor_schedule import MonitorSchedule, MonitorScheduleCreate, BulkScheduleCreate
from app.services.business_service import business_service
from app.services.biz_item_service import biz_item_service
from app.services.schedule_service import schedule_service

router = APIRouter(prefix="/api/v1", tags=["items"])


@router.post("/businesses/{business_id}/items", response_model=BizItem, status_code=201)
def create_item(business_id: int, data: BizItemCreate, db: Session = Depends(get_db)):
    """아이템 생성"""
    # 업체 존재 확인
    business = business_service.get_by_id(db, business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    # business_id 강제 설정
    data.business_id = business_id

    # 중복 체크
    existing = biz_item_service.get_by_biz_item_id(db, business_id, data.biz_item_id)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Item with biz_item_id '{data.biz_item_id}' already exists in this business"
        )

    return biz_item_service.create(db, data)


@router.get("/items/{item_id}", response_model=BizItemWithSchedules)
def get_item(item_id: int, db: Session = Depends(get_db)):
    """아이템 상세 조회 (일정 포함)"""
    item = biz_item_service.get_by_id(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.put("/items/{item_id}", response_model=BizItem)
def update_item(item_id: int, data: BizItemUpdate, db: Session = Depends(get_db)):
    """아이템 수정"""
    item = biz_item_service.update(db, item_id, data)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_db)):
    """아이템 삭제 (일정 모두 삭제)"""
    success = biz_item_service.delete(db, item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found")
    return None


@router.get("/items/{item_id}/schedules", response_model=List[MonitorSchedule])
def get_item_schedules(item_id: int, db: Session = Depends(get_db)):
    """아이템의 일정 목록 조회"""
    item = biz_item_service.get_by_id(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    schedules = schedule_service.get_by_item(db, item_id)
    # account_name 채우기
    for schedule in schedules:
        if schedule.account:
            schedule.account_name = schedule.account.name
    return schedules


@router.post("/items/{item_id}/schedules", response_model=MonitorSchedule, status_code=201)
def create_schedule(item_id: int, data: MonitorScheduleCreate, db: Session = Depends(get_db)):
    """일정 생성"""
    item = biz_item_service.get_by_id(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # biz_item_id 강제 설정
    data.biz_item_id = item_id

    # 중복 체크 (같은 날짜, 같은 계정의 일정만 중복으로 처리)
    existing = schedule_service.get_by_date(db, item_id, data.date)
    if existing and existing.account_id == data.account_id:
        raise HTTPException(
            status_code=400,
            detail=f"Schedule for date '{data.date}' with this account already exists"
        )

    schedule = schedule_service.create(db, data)
    # account_name 채우기
    if schedule.account:
        schedule.account_name = schedule.account.name
    return schedule


@router.post("/items/{item_id}/schedules/bulk", response_model=List[MonitorSchedule], status_code=201)
def create_bulk_schedules(item_id: int, data: BulkScheduleCreate, db: Session = Depends(get_db)):
    """일정 일괄 생성"""
    item = biz_item_service.get_by_id(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # biz_item_id 강제 설정
    data.biz_item_id = item_id

    schedules = schedule_service.create_bulk(db, data)
    # account_name 채우기
    for schedule in schedules:
        if schedule.account:
            schedule.account_name = schedule.account.name
    return schedules

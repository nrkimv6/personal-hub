"""
쿠팡 여행상품 모니터링 API 라우트.

상품(target) 등록/조회/삭제 및 모니터링 일정 CRUD를 제공합니다.
"""
import json
from datetime import date as date_type
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.business import Business
from app.models.biz_item import BizItem
from app.models.monitor_schedule import MonitorSchedule
from app.models.service_account import ServiceAccount
from app.modules.coupang_travel.utils.url_parser import parse_coupang_url
from app.services.schedule_service import ScheduleService

router = APIRouter(prefix="/api/v1/coupang", tags=["쿠팡 여행"])

_schedule_service = ScheduleService()


# ──────────────────────────────────────────────
# 요청/응답 스키마
# ──────────────────────────────────────────────

class CreateTargetRequest(BaseModel):
    url: str
    vendor_item_package_id: str
    name: str


class CreateTargetResponse(BaseModel):
    id: int
    product_id: str


class CreateScheduleRequest(BaseModel):
    biz_item_id: int
    dates: List[str]
    service_account_id: Optional[int] = None


class CreateScheduleResponse(BaseModel):
    created: int


class TargetItem(BaseModel):
    id: int
    product_id: str
    name: str
    business_pk: int
    is_enabled: bool


class ScheduleItem(BaseModel):
    id: int
    date: str
    is_enabled: bool
    is_active: bool
    product_id: Optional[str]
    item_name: Optional[str]
    business_name: Optional[str]
    service_account_id: Optional[int]


class CoupangStatusSummary(BaseModel):
    total_schedules: int
    enabled_schedules: int
    active_schedules: int


def _get_coupang_schedule_or_404(schedule_id: int, db: Session) -> MonitorSchedule:
    """쿠팡 서비스 소유 스케줄만 조회."""
    schedule = (
        db.query(MonitorSchedule)
        .join(BizItem, MonitorSchedule.biz_item_id == BizItem.id)
        .join(Business, BizItem.business_id == Business.id)
        .filter(
            MonitorSchedule.id == schedule_id,
            Business.service_type == "coupang",
        )
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=404, detail="MonitorSchedule not found")
    return schedule


# ──────────────────────────────────────────────
# 상품 API
# ──────────────────────────────────────────────

@router.post("/targets", status_code=status.HTTP_201_CREATED, response_model=CreateTargetResponse)
def create_target(body: CreateTargetRequest, db: Session = Depends(get_db)):
    """쿠팡 여행상품 등록."""
    try:
        parsed = parse_coupang_url(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    product_id = parsed["product_id"]
    business_id_str = f"cp:{product_id}"

    # 기존 Business 조회 또는 생성
    business = db.query(Business).filter(Business.business_id == business_id_str).first()
    if not business:
        business = Business(
            business_id=business_id_str,
            name=body.name,
            service_type="coupang",
        )
        db.add(business)
        db.flush()

    # BizItem 조회 또는 생성
    biz_item = db.query(BizItem).filter(
        BizItem.business_id == business.id,
        BizItem.biz_item_id == product_id,
    ).first()
    if not biz_item:
        extra = json.dumps({
            "vendor_item_package_id": body.vendor_item_package_id,
            "product_id": product_id,
        })
        biz_item = BizItem(
            business_id=business.id,
            biz_item_id=product_id,
            name=body.name,
            extra_desc_json=extra,
        )
        db.add(biz_item)
        db.flush()
    else:
        # vendor_item_package_id 업데이트
        extra = json.dumps({
            "vendor_item_package_id": body.vendor_item_package_id,
            "product_id": product_id,
        })
        biz_item.extra_desc_json = extra

    db.commit()
    db.refresh(biz_item)

    return CreateTargetResponse(id=biz_item.id, product_id=product_id)


@router.get("/targets", response_model=List[TargetItem])
def list_targets(db: Session = Depends(get_db)):
    """쿠팡 상품 목록 조회."""
    businesses = db.query(Business).filter(Business.service_type == "coupang").all()
    result = []
    for biz in businesses:
        items = db.query(BizItem).filter(BizItem.business_id == biz.id).all()
        for item in items:
            result.append(TargetItem(
                id=item.id,
                product_id=item.biz_item_id,
                name=item.name,
                business_pk=biz.id,
                is_enabled=item.is_enabled,
            ))
    return result


@router.delete("/targets/{biz_item_id}", status_code=status.HTTP_200_OK)
def delete_target(biz_item_id: int, db: Session = Depends(get_db)):
    """상품(BizItem) 삭제 — cascade로 MonitorSchedule도 삭제됨."""
    item = db.query(BizItem).filter(BizItem.id == biz_item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="BizItem not found")

    # Business도 cascade 정리 (BizItem이 없어지면 Business도 삭제)
    business = db.query(Business).filter(Business.id == item.business_id).first()

    db.delete(item)
    db.flush()

    # Business의 다른 BizItem이 없으면 Business도 삭제
    if business:
        remaining = db.query(BizItem).filter(BizItem.business_id == business.id).count()
        if remaining == 0:
            db.delete(business)

    db.commit()
    return {"deleted": biz_item_id}


# ──────────────────────────────────────────────
# 일정 API
# ──────────────────────────────────────────────

@router.post("/schedules", status_code=status.HTTP_201_CREATED, response_model=CreateScheduleResponse)
def create_schedules(body: CreateScheduleRequest, db: Session = Depends(get_db)):
    """모니터링 일정 등록."""
    # BizItem 존재 확인
    biz_item = db.query(BizItem).filter(BizItem.id == body.biz_item_id).first()
    if not biz_item:
        raise HTTPException(status_code=400, detail="BizItem not found")

    # 계정 검증 (service_account_id가 지정된 경우에만)
    if body.service_account_id is not None:
        account = db.query(ServiceAccount).filter(
            ServiceAccount.id == body.service_account_id
        ).first()
        if not account:
            raise HTTPException(status_code=400, detail="ServiceAccount not found")
        if account.service_type != "coupang":
            raise HTTPException(
                status_code=400,
                detail=f"ServiceAccount service_type must be 'coupang', got '{account.service_type}'"
            )
        if not account.is_logged_in:
            raise HTTPException(status_code=400, detail="ServiceAccount is not logged in")

    created = 0
    for date in body.dates:
        # 중복 확인
        existing = db.query(MonitorSchedule).filter(
            MonitorSchedule.biz_item_id == body.biz_item_id,
            MonitorSchedule.date == date,
        ).first()
        if existing:
            continue

        schedule = MonitorSchedule(
            biz_item_id=body.biz_item_id,
            date=date,
            service_account_id=body.service_account_id,
            is_enabled=True,
        )
        db.add(schedule)
        created += 1

    db.commit()
    return CreateScheduleResponse(created=created)


@router.get("/schedules", response_model=List[ScheduleItem])
def list_schedules(db: Session = Depends(get_db)):
    """쿠팡 모니터링 일정 목록 조회."""
    contexts = _schedule_service.get_all_with_context(db, service_type="coupang")
    result = []
    for ctx in contexts:
        result.append(ScheduleItem(
            id=ctx["id"],
            date=ctx["date"],
            is_enabled=ctx["is_enabled"],
            is_active=ctx.get("is_active", False),
            product_id=ctx.get("item_biz_item_id"),
            item_name=ctx.get("item_name"),
            business_name=ctx.get("business_name"),
            service_account_id=ctx.get("service_account_id"),
        ))
    return result


@router.post("/schedules/{schedule_id}/enable", status_code=status.HTTP_200_OK)
def enable_schedule(schedule_id: int, db: Session = Depends(get_db)):
    """쿠팡 모니터링 일정 활성화."""
    _get_coupang_schedule_or_404(schedule_id, db)
    updated = _schedule_service.enable(db, schedule_id)
    if not updated:
        raise HTTPException(status_code=404, detail="MonitorSchedule not found")
    return {"id": updated.id, "is_enabled": updated.is_enabled}


@router.post("/schedules/{schedule_id}/disable", status_code=status.HTTP_200_OK)
def disable_schedule(schedule_id: int, db: Session = Depends(get_db)):
    """쿠팡 모니터링 일정 비활성화."""
    _get_coupang_schedule_or_404(schedule_id, db)
    updated = _schedule_service.disable(db, schedule_id)
    if not updated:
        raise HTTPException(status_code=404, detail="MonitorSchedule not found")
    return {"id": updated.id, "is_enabled": updated.is_enabled}


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_200_OK)
def delete_schedule(schedule_id: int, db: Session = Depends(get_db)):
    """모니터링 일정 삭제."""
    schedule = _get_coupang_schedule_or_404(schedule_id, db)
    db.delete(schedule)
    db.commit()
    return {"deleted": schedule_id}


@router.get("/status", response_model=CoupangStatusSummary)
def get_coupang_status(db: Session = Depends(get_db)):
    """쿠팡 모니터링 상태 요약."""
    stats = (
        db.query(
            func.count(MonitorSchedule.id).label("total_schedules"),
            func.sum(
                case((MonitorSchedule.is_enabled.is_(True), 1), else_=0)
            ).label("enabled_schedules"),
            func.sum(
                case(
                    (
                        and_(
                            MonitorSchedule.is_enabled.is_(True),
                            MonitorSchedule.is_active.is_(True),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("active_schedules"),
        )
        .join(BizItem, MonitorSchedule.biz_item_id == BizItem.id)
        .join(Business, BizItem.business_id == Business.id)
        .filter(Business.service_type == "coupang")
        .first()
    )

    return CoupangStatusSummary(
        total_schedules=int(stats.total_schedules or 0),
        enabled_schedules=int(stats.enabled_schedules or 0),
        active_schedules=int(stats.active_schedules or 0),
    )


@router.post("/schedules/cleanup", status_code=status.HTTP_200_OK)
def cleanup_schedules(db: Session = Depends(get_db)):
    """과거 날짜 및 null 계정 쿠팡 스케줄 일괄 삭제."""
    today = date_type.today().isoformat()
    schedules_to_delete = (
        db.query(MonitorSchedule)
        .join(BizItem, MonitorSchedule.biz_item_id == BizItem.id)
        .join(Business, BizItem.business_id == Business.id)
        .filter(
            Business.service_type == "coupang",
            (MonitorSchedule.service_account_id.is_(None))
            | (MonitorSchedule.date < today),
        )
        .all()
    )
    count = len(schedules_to_delete)
    for schedule in schedules_to_delete:
        db.delete(schedule)
    db.commit()
    return {"deleted": count}

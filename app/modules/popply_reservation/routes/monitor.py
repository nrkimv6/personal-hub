"""POPPLY reservation monitor routes."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.business import Business
from app.models.biz_item import BizItem
from app.models.monitor_schedule import MonitorSchedule
from app.models.monitoring_event import MonitoringEvent
from app.modules.availability.services.event_writer import write_availability_event
from app.modules.popply_reservation.services.adapter import PopplyReservationAdapter
from app.modules.popply_reservation.utils.url_parser import parse_popply_reservation_url

router = APIRouter(prefix="/api/v1/popply", tags=["POPPLY 예약"])
adapter = PopplyReservationAdapter()


class CreateTargetRequest(BaseModel):
    source_url: str
    name: Optional[str] = None


class TargetResponse(BaseModel):
    id: int
    store_id: str
    name: str
    source_url: str
    schedule_group: str
    reservation_type: str
    is_enabled: bool


class CreateScheduleRequest(BaseModel):
    biz_item_id: int
    dates: list[str]


class CreateScheduleResponse(BaseModel):
    created: int


class ScheduleResponse(BaseModel):
    id: int
    biz_item_id: int
    date: str
    is_enabled: bool
    is_active: bool
    run_status: str
    last_check_time: Optional[str] = None
    last_event_at: Optional[str] = None
    last_event_status: Optional[str] = None
    item_name: Optional[str] = None
    store_id: Optional[str] = None
    schedule_group: Optional[str] = None


class CheckNowResponse(BaseModel):
    schedule_id: int
    status: str
    available_count: int
    latest_event_id: Optional[int] = None


def _load_extra(item: BizItem) -> dict:
    if not item.extra_desc_json:
        return {}
    try:
        parsed = json.loads(item.extra_desc_json)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _target_response(item: BizItem) -> TargetResponse:
    extra = _load_extra(item)
    return TargetResponse(
        id=item.id,
        store_id=str(extra.get("store_id") or item.biz_item_id),
        name=item.name,
        source_url=item.base_url or "",
        schedule_group=str(extra.get("schedule_group") or ""),
        reservation_type=str(extra.get("reservation_type") or "PRE"),
        is_enabled=bool(item.is_enabled),
    )


def _popply_schedule_or_404(db: Session, schedule_id: int) -> MonitorSchedule:
    schedule = (
        db.query(MonitorSchedule)
        .join(BizItem, MonitorSchedule.biz_item_id == BizItem.id)
        .join(Business, BizItem.business_id == Business.id)
        .filter(MonitorSchedule.id == schedule_id, Business.service_type == "popply")
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=404, detail="MonitorSchedule not found")
    return schedule


def _latest_event(db: Session, schedule_id: int) -> Optional[MonitoringEvent]:
    return (
        db.query(MonitoringEvent)
        .filter(MonitoringEvent.schedule_id == schedule_id)
        .order_by(MonitoringEvent.timestamp.desc(), MonitoringEvent.id.desc())
        .first()
    )


def _schedule_response(db: Session, schedule: MonitorSchedule) -> ScheduleResponse:
    item = schedule.biz_item
    extra = _load_extra(item)
    latest = _latest_event(db, schedule.id)
    return ScheduleResponse(
        id=schedule.id,
        biz_item_id=item.id,
        date=schedule.date,
        is_enabled=bool(schedule.is_enabled),
        is_active=bool(schedule.is_active),
        run_status=schedule.run_status or "idle",
        last_check_time=schedule.last_check_time.isoformat() if schedule.last_check_time else None,
        last_event_at=latest.timestamp.isoformat() if latest else None,
        last_event_status=latest.status if latest else None,
        item_name=item.name,
        store_id=str(extra.get("store_id") or ""),
        schedule_group=str(extra.get("schedule_group") or ""),
    )


@router.post("/targets", status_code=status.HTTP_201_CREATED, response_model=TargetResponse)
def create_target(body: CreateTargetRequest, db: Session = Depends(get_db)):
    try:
        parsed = parse_popply_reservation_url(body.source_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    business = (
        db.query(Business)
        .filter(Business.business_id == f"popply:{parsed.store_id}")
        .first()
    )
    if not business:
        business = Business(
            business_id=f"popply:{parsed.store_id}",
            name=body.name or f"POPPLY {parsed.store_id}",
            service_type="popply",
            category="reservation",
        )
        db.add(business)
        db.flush()
    else:
        business.name = body.name or business.name
        business.updated_at = datetime.now()

    item_key = f"{parsed.store_id}:{parsed.target_schedule_group}"
    item = (
        db.query(BizItem)
        .filter(BizItem.business_id == business.id, BizItem.biz_item_id == item_key)
        .first()
    )
    extra = {
        "store_id": parsed.store_id,
        "reservation_type": parsed.reservation_type,
        "source_hash": parsed.source_hash,
        "schedule_group": parsed.target_schedule_group,
    }
    if not item:
        item = BizItem(
            business_id=business.id,
            biz_item_id=item_key,
            name=body.name or f"POPPLY {parsed.store_id}",
            base_url=body.source_url,
            extra_desc_json=json.dumps(extra, ensure_ascii=False),
        )
        db.add(item)
    else:
        item.name = body.name or item.name
        item.base_url = body.source_url
        item.extra_desc_json = json.dumps(extra, ensure_ascii=False)
        item.updated_at = datetime.now()

    db.commit()
    db.refresh(item)
    return _target_response(item)


@router.get("/targets", response_model=list[TargetResponse])
def list_targets(db: Session = Depends(get_db)):
    items = (
        db.query(BizItem)
        .join(Business, BizItem.business_id == Business.id)
        .filter(Business.service_type == "popply")
        .order_by(BizItem.created_at.desc(), BizItem.id.desc())
        .all()
    )
    return [_target_response(item) for item in items]


@router.delete("/targets/{target_id}")
def delete_target(target_id: int, db: Session = Depends(get_db)):
    item = (
        db.query(BizItem)
        .join(Business, BizItem.business_id == Business.id)
        .filter(BizItem.id == target_id, Business.service_type == "popply")
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Target not found")
    db.delete(item)
    db.commit()
    return {"deleted": target_id}


@router.post("/schedules", status_code=status.HTTP_201_CREATED, response_model=CreateScheduleResponse)
def create_schedules(body: CreateScheduleRequest, db: Session = Depends(get_db)):
    item = (
        db.query(BizItem)
        .join(Business, BizItem.business_id == Business.id)
        .filter(BizItem.id == body.biz_item_id, Business.service_type == "popply")
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Target not found")
    created = 0
    for date in body.dates:
        exists = (
            db.query(MonitorSchedule)
            .filter(MonitorSchedule.biz_item_id == item.id, MonitorSchedule.date == date)
            .first()
        )
        if exists:
            continue
        db.add(MonitorSchedule(biz_item_id=item.id, date=date, is_enabled=True))
        created += 1
    db.commit()
    return CreateScheduleResponse(created=created)


@router.get("/schedules", response_model=list[ScheduleResponse])
def list_schedules(db: Session = Depends(get_db)):
    rows = (
        db.query(MonitorSchedule, BizItem)
        .join(BizItem, MonitorSchedule.biz_item_id == BizItem.id)
        .join(Business, BizItem.business_id == Business.id)
        .filter(Business.service_type == "popply")
        .order_by(MonitorSchedule.date.desc(), MonitorSchedule.id.desc())
        .all()
    )
    responses: list[ScheduleResponse] = []
    for schedule, item in rows:
        schedule.biz_item = item
        responses.append(_schedule_response(db, schedule))
    return responses


@router.post("/schedules/{schedule_id}/enable", response_model=ScheduleResponse)
def enable_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = _popply_schedule_or_404(db, schedule_id)
    schedule.is_enabled = True
    schedule.updated_at = datetime.now()
    db.commit()
    db.refresh(schedule)
    return _schedule_response(db, schedule)


@router.post("/schedules/{schedule_id}/disable", response_model=ScheduleResponse)
def disable_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = _popply_schedule_or_404(db, schedule_id)
    schedule.is_enabled = False
    schedule.updated_at = datetime.now()
    db.commit()
    db.refresh(schedule)
    return _schedule_response(db, schedule)


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = _popply_schedule_or_404(db, schedule_id)
    db.delete(schedule)
    db.commit()
    return {"deleted": schedule_id}


@router.get("/schedules/{schedule_id}/status", response_model=ScheduleResponse)
def get_schedule_status(schedule_id: int, db: Session = Depends(get_db)):
    schedule = _popply_schedule_or_404(db, schedule_id)
    return _schedule_response(db, schedule)


@router.post("/schedules/{schedule_id}/check-now", response_model=CheckNowResponse)
async def check_now(schedule_id: int, db: Session = Depends(get_db)):
    schedule = _popply_schedule_or_404(db, schedule_id)
    item = schedule.biz_item
    extra = _load_extra(item)
    result = await adapter.check(
        store_id=str(extra.get("store_id") or item.biz_item_id),
        reservation_type=str(extra.get("reservation_type") or "PRE"),
        target_schedule_group=str(extra.get("schedule_group") or ""),
        schedule_date=schedule.date,
    )
    event_id = write_availability_event(schedule.id, result)
    schedule.last_check_time = datetime.now()
    schedule.run_status = "idle"
    db.commit()
    latest = _latest_event(db, schedule.id)
    return CheckNowResponse(
        schedule_id=schedule.id,
        status=latest.status if latest else ("error" if result.error_message else "no_slots"),
        available_count=latest.available_count if latest else (result.available_count or 0),
        latest_event_id=event_id,
    )

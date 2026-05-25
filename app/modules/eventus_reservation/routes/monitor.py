"""Eventus reservation monitor routes.

Endpoints:
  POST   /api/v1/eventus/analyze          — 1-shot bundle/time candidate extraction
  POST   /api/v1/eventus/targets          — create target (Business + BizItem)
  GET    /api/v1/eventus/targets          — list targets
  DELETE /api/v1/eventus/targets/{id}     — delete target
  POST   /api/v1/eventus/schedules        — create schedules
  GET    /api/v1/eventus/schedules        — list schedules
  POST   /api/v1/eventus/schedules/{id}/enable
  POST   /api/v1/eventus/schedules/{id}/disable
  DELETE /api/v1/eventus/schedules/{id}
  GET    /api/v1/eventus/schedules/{id}/status
  POST   /api/v1/eventus/schedules/{id}/check-now
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.biz_item import BizItem
from app.models.business import Business
from app.models.monitor_schedule import MonitorSchedule
from app.models.monitoring_event import MonitoringEvent
from app.modules.availability.services.event_writer import write_availability_event
from app.modules.eventus_reservation.services.adapter import EventusReservationAdapter
from app.modules.eventus_reservation.services.analyzer import EventusAnalyzer
from app.modules.eventus_reservation.utils.url_parser import normalize_eventus_input

router = APIRouter(prefix="/api/v1/eventus", tags=["Eventus 잔여석"])
_adapter = EventusReservationAdapter()
_analyzer = EventusAnalyzer()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    input: str  # event_id (digits) or full URL


class SlotInfo(BaseModel):
    bundle_id: str
    time_label: Optional[str] = None
    is_closed: bool = False
    closed_text: Optional[str] = None
    urgency_hint: Optional[str] = None


class AnalyzeResponse(BaseModel):
    event_id: Optional[str]
    source_url: Optional[str]
    organizer_slug: Optional[str]
    channel_name: Optional[str]
    title: Optional[str]
    bundles: list[str]
    slots: list[SlotInfo]
    closed_token_counts: int
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    fetch_method: str = "anonymous_html"


class CreateTargetRequest(BaseModel):
    source_url: str
    name: Optional[str] = None
    event_id: Optional[str] = None
    organizer_slug: Optional[str] = None
    channel_name: Optional[str] = None
    title: Optional[str] = None
    bundle_ids: Optional[list[str]] = None
    selected_bundle_id: Optional[str] = None
    selected_time_key: Optional[str] = None


class TargetResponse(BaseModel):
    id: int
    event_id: Optional[str]
    name: str
    source_url: str
    channel_name: Optional[str]
    organizer_slug: Optional[str]
    selected_bundle_id: Optional[str]
    selected_time_key: Optional[str]
    bundle_ids: list[str]
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
    event_id: Optional[str] = None
    selected_bundle_id: Optional[str] = None
    selected_time_key: Optional[str] = None


class CheckNowResponse(BaseModel):
    schedule_id: int
    status: str
    available_count: int
    latest_event_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        event_id=str(extra.get("event_id") or ""),
        name=item.name,
        source_url=item.base_url or extra.get("source_url") or "",
        channel_name=extra.get("channel_name"),
        organizer_slug=extra.get("organizer_slug"),
        selected_bundle_id=extra.get("selected_bundle_id"),
        selected_time_key=extra.get("selected_time_key"),
        bundle_ids=extra.get("bundle_ids") or [],
        is_enabled=bool(item.is_enabled),
    )


def _eventus_schedule_or_404(db: Session, schedule_id: int) -> MonitorSchedule:
    schedule = (
        db.query(MonitorSchedule)
        .join(BizItem, MonitorSchedule.biz_item_id == BizItem.id)
        .join(Business, BizItem.business_id == Business.id)
        .filter(MonitorSchedule.id == schedule_id, Business.service_type == "eventus")
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
        event_id=str(extra.get("event_id") or ""),
        selected_bundle_id=extra.get("selected_bundle_id"),
        selected_time_key=extra.get("selected_time_key"),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_event(body: AnalyzeRequest):
    """Analyze event page once and return meta/bundle/time candidates."""
    try:
        inp = normalize_eventus_input(body.input)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = await _analyzer.analyze(inp)
    return AnalyzeResponse(
        event_id=result.event_id,
        source_url=result.source_url,
        organizer_slug=result.organizer_slug,
        channel_name=result.channel_name,
        title=result.title,
        bundles=result.bundles,
        slots=[
            SlotInfo(
                bundle_id=s.bundle_id,
                time_label=s.time_label,
                is_closed=s.is_closed,
                closed_text=s.closed_text,
                urgency_hint=s.urgency_hint,
            )
            for s in result.slots
        ],
        closed_token_counts=result.closed_token_counts,
        error_code=result.error_code,
        error_message=result.error_message,
        fetch_method=result.fetch_method,
    )


@router.post("/targets", status_code=status.HTTP_201_CREATED, response_model=TargetResponse)
def create_target(body: CreateTargetRequest, db: Session = Depends(get_db)):
    """Create Business + BizItem for an Eventus event target."""
    # Parse/validate source_url
    try:
        inp = normalize_eventus_input(body.source_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    event_id = body.event_id or inp.event_id
    organizer_slug = body.organizer_slug or inp.organizer_slug
    channel_name = body.channel_name
    display_name = body.name or body.title or f"Eventus {event_id}"

    business_id_key = f"eventus:{event_id}"
    business = (
        db.query(Business)
        .filter(Business.business_id == business_id_key)
        .first()
    )
    if not business:
        business = Business(
            business_id=business_id_key,
            name=channel_name or organizer_slug or display_name,
            service_type="eventus",
            category="reservation",
        )
        db.add(business)
        db.flush()
    else:
        if channel_name:
            business.name = channel_name
        business.updated_at = datetime.now()

    extra: dict = {
        "event_id": event_id,
        "source_url": body.source_url,
        "organizer_slug": organizer_slug,
        "channel_name": channel_name,
        "title": body.title,
        "bundle_ids": body.bundle_ids or [],
        "selected_bundle_id": body.selected_bundle_id,
        "selected_time_key": body.selected_time_key,
    }

    item_key = f"eventus:{event_id}"
    item = (
        db.query(BizItem)
        .filter(BizItem.business_id == business.id, BizItem.biz_item_id == item_key)
        .first()
    )
    if not item:
        item = BizItem(
            business_id=business.id,
            biz_item_id=item_key,
            name=body.title or display_name,
            base_url=body.source_url,
            extra_desc_json=json.dumps(extra, ensure_ascii=False),
        )
        db.add(item)
    else:
        item.name = body.title or item.name
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
        .filter(Business.service_type == "eventus")
        .order_by(BizItem.created_at.desc(), BizItem.id.desc())
        .all()
    )
    return [_target_response(item) for item in items]


@router.delete("/targets/{target_id}")
def delete_target(target_id: int, db: Session = Depends(get_db)):
    item = (
        db.query(BizItem)
        .join(Business, BizItem.business_id == Business.id)
        .filter(BizItem.id == target_id, Business.service_type == "eventus")
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
        .filter(BizItem.id == body.biz_item_id, Business.service_type == "eventus")
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
        .filter(Business.service_type == "eventus")
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
    schedule = _eventus_schedule_or_404(db, schedule_id)
    schedule.is_enabled = True
    schedule.updated_at = datetime.now()
    db.commit()
    db.refresh(schedule)
    return _schedule_response(db, schedule)


@router.post("/schedules/{schedule_id}/disable", response_model=ScheduleResponse)
def disable_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = _eventus_schedule_or_404(db, schedule_id)
    schedule.is_enabled = False
    schedule.updated_at = datetime.now()
    db.commit()
    db.refresh(schedule)
    return _schedule_response(db, schedule)


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = _eventus_schedule_or_404(db, schedule_id)
    db.delete(schedule)
    db.commit()
    return {"deleted": schedule_id}


@router.get("/schedules/{schedule_id}/status", response_model=ScheduleResponse)
def get_schedule_status(schedule_id: int, db: Session = Depends(get_db)):
    schedule = _eventus_schedule_or_404(db, schedule_id)
    return _schedule_response(db, schedule)


@router.post("/schedules/{schedule_id}/check-now", response_model=CheckNowResponse)
async def check_now(schedule_id: int, db: Session = Depends(get_db)):
    schedule = _eventus_schedule_or_404(db, schedule_id)
    item = schedule.biz_item
    extra = _load_extra(item)

    source_url = extra.get("source_url") or item.base_url
    if not source_url:
        raise HTTPException(status_code=400, detail="source_url missing in target extra")

    result = await _adapter.check(
        source_url=source_url,
        schedule_date=schedule.date,
        target_bundle_id=extra.get("selected_bundle_id"),
        target_time_key=extra.get("selected_time_key"),
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

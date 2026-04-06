"""Naver popup URL monitor routes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.popup_url_monitor import PopupUrlMonitor
from app.models.service_account import ServiceAccount
from app.modules.naver_popup_monitor.schemas import (
    FallbackStrategyLiteral,
    RequestProfileLiteral,
)
from app.modules.naver_popup_monitor.services.monitor_service import PopupMonitorService

MonitoringModeLiteral = Literal["anonymous", "legacy"]

router = APIRouter(prefix="/api/v1/naver-popup", tags=["네이버 팝업 URL 모니터"])
monitor_service = PopupMonitorService()


class PopupMonitorCreateRequest(BaseModel):
    name: str | None = None
    url: str
    request_profile: RequestProfileLiteral = "A"
    fallback_strategy: FallbackStrategyLiteral = "reinforce"
    proxy_enabled: bool = False
    notify_on_new: bool = True
    min_new_count: int = Field(default=1, ge=1)
    monitoring_mode: MonitoringModeLiteral = "anonymous"
    service_account_id: int | None = None
    browser_fallback_enabled: bool = False
    is_enabled: bool = True


class PopupMonitorUpdateRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    request_profile: RequestProfileLiteral | None = None
    fallback_strategy: FallbackStrategyLiteral | None = None
    proxy_enabled: bool | None = None
    notify_on_new: bool | None = None
    min_new_count: int | None = Field(default=None, ge=1)
    monitoring_mode: MonitoringModeLiteral | None = None
    service_account_id: int | None = None
    browser_fallback_enabled: bool | None = None
    is_enabled: bool | None = None


class PopupMonitorResponse(BaseModel):
    id: int
    name: str | None
    url: str
    request_profile: RequestProfileLiteral
    fallback_strategy: FallbackStrategyLiteral
    proxy_enabled: bool
    notify_on_new: bool
    min_new_count: int
    monitoring_mode: MonitoringModeLiteral
    service_account_id: int | None
    browser_fallback_enabled: bool
    is_enabled: bool
    latest_snapshot_hash: str | None
    latest_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PopupMonitorCheckNowResponse(BaseModel):
    monitor_id: int
    run_id: int
    status: str
    new_count: int = 0
    has_new: bool = False
    request_profile: str | None = None
    proxy_url: str | None = None
    fallback_applied: bool = False
    error_message: str | None = None


class PopupMonitorRunItem(BaseModel):
    id: int
    monitor_id: int
    status: str
    new_count: int
    has_new: bool
    proxy_url: str | None = None
    request_profile: str | None = None
    fallback_applied: bool
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    snapshot: dict | None = None


class PopupMonitorLatestResponse(BaseModel):
    monitor_id: int
    latest_checked_at: datetime | None = None
    latest_snapshot_hash: str | None = None
    item_count: int
    snapshot: dict | None = None
    last_run: PopupMonitorRunItem | None = None


def _get_monitor_or_404(monitor_id: int, db: Session) -> PopupUrlMonitor:
    monitor = db.query(PopupUrlMonitor).filter(PopupUrlMonitor.id == monitor_id).first()
    if not monitor:
        raise HTTPException(status_code=404, detail="Popup monitor not found")
    return monitor


def _validate_service_account(service_account_id: int | None, db: Session) -> None:
    if service_account_id is None:
        return

    account = db.query(ServiceAccount).filter(ServiceAccount.id == service_account_id).first()
    if not account:
        raise HTTPException(status_code=400, detail="ServiceAccount not found")
    if account.service_type != "naver":
        raise HTTPException(
            status_code=400,
            detail=f"ServiceAccount service_type must be 'naver', got '{account.service_type}'",
        )


@router.post("/monitors", status_code=status.HTTP_201_CREATED, response_model=PopupMonitorResponse)
def create_monitor(body: PopupMonitorCreateRequest, db: Session = Depends(get_db)):
    _validate_service_account(body.service_account_id, db)

    monitor = PopupUrlMonitor(
        name=body.name,
        url=body.url,
        request_profile=body.request_profile,
        fallback_strategy=body.fallback_strategy,
        proxy_enabled=body.proxy_enabled,
        notify_on_new=body.notify_on_new,
        min_new_count=body.min_new_count,
        monitoring_mode=body.monitoring_mode,
        service_account_id=body.service_account_id,
        browser_fallback_enabled=body.browser_fallback_enabled,
        is_enabled=body.is_enabled,
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    return monitor


@router.get("/monitors", response_model=list[PopupMonitorResponse])
def list_monitors(db: Session = Depends(get_db)):
    return (
        db.query(PopupUrlMonitor)
        .order_by(PopupUrlMonitor.created_at.desc(), PopupUrlMonitor.id.desc())
        .all()
    )


@router.get("/monitors/{monitor_id}", response_model=PopupMonitorResponse)
def get_monitor(monitor_id: int, db: Session = Depends(get_db)):
    return _get_monitor_or_404(monitor_id, db)


@router.put("/monitors/{monitor_id}", response_model=PopupMonitorResponse)
def update_monitor(
    monitor_id: int,
    body: PopupMonitorUpdateRequest,
    db: Session = Depends(get_db),
):
    monitor = _get_monitor_or_404(monitor_id, db)

    values = body.model_dump(exclude_unset=True)
    if "service_account_id" in values:
        _validate_service_account(values["service_account_id"], db)

    for field, value in values.items():
        setattr(monitor, field, value)
    monitor.updated_at = datetime.now()

    db.commit()
    db.refresh(monitor)
    return monitor


@router.delete("/monitors/{monitor_id}", status_code=status.HTTP_200_OK)
def delete_monitor(monitor_id: int, db: Session = Depends(get_db)):
    monitor = _get_monitor_or_404(monitor_id, db)
    db.delete(monitor)
    db.commit()
    return {"deleted": monitor_id}


@router.post("/monitors/{monitor_id}/enable", response_model=PopupMonitorResponse)
def enable_monitor(monitor_id: int, db: Session = Depends(get_db)):
    monitor = _get_monitor_or_404(monitor_id, db)
    monitor.is_enabled = True
    monitor.updated_at = datetime.now()
    db.commit()
    db.refresh(monitor)
    return monitor


@router.post("/monitors/{monitor_id}/disable", response_model=PopupMonitorResponse)
def disable_monitor(monitor_id: int, db: Session = Depends(get_db)):
    monitor = _get_monitor_or_404(monitor_id, db)
    monitor.is_enabled = False
    monitor.updated_at = datetime.now()
    db.commit()
    db.refresh(monitor)
    return monitor


@router.post(
    "/monitors/{monitor_id}/check-now",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PopupMonitorCheckNowResponse,
)
async def check_now(monitor_id: int, db: Session = Depends(get_db)):
    monitor = _get_monitor_or_404(monitor_id, db)
    outcome = await monitor_service.run_monitor_once(db, monitor, trigger="manual")
    return PopupMonitorCheckNowResponse(**outcome.to_dict())


@router.get(
    "/monitors/{monitor_id}/latest",
    response_model=PopupMonitorLatestResponse,
)
def get_latest(monitor_id: int, db: Session = Depends(get_db)):
    _get_monitor_or_404(monitor_id, db)
    payload = monitor_service.get_latest_payload(db, monitor_id)
    return PopupMonitorLatestResponse(**payload)


@router.get(
    "/monitors/{monitor_id}/runs",
    response_model=list[PopupMonitorRunItem],
)
def get_runs(
    monitor_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    _get_monitor_or_404(monitor_id, db)
    limit = max(1, min(limit, 200))
    payload = monitor_service.list_runs_payload(db, monitor_id, limit=limit)
    return [PopupMonitorRunItem(**row) for row in payload]

"""Tracking item API routes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from app.core.auth import UserInfo, require_admin
from app.database import get_db
from app.models.plan_record import PlanRecord
from app.models.tracking_item import TrackingItem, TrackingItemPlanLink
from app.schemas.tracking import (
    LinkedPlan,
    LinkPlansRequest,
    TrackingItemCreate,
    TrackingItemListResponse,
    TrackingItemResponse,
    TrackingItemUpdate,
    TrackingStatus,
)
from app.services.tracking_service import (
    complete_tracking_item,
    create_tracking_item,
    list_tracking_items,
    reopen_tracking_item,
    serialize_tracking_item,
    update_tracking_item,
)

router = APIRouter(prefix="/api/v1/tracking", tags=["tracking"])


def _get_item_or_404(db: Session, item_id: int) -> TrackingItem:
    item = (
        db.query(TrackingItem)
        .options(
            selectinload(TrackingItem.linked_plans).selectinload(TrackingItemPlanLink.plan_record)
        )
        .filter(TrackingItem.id == item_id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Tracking item not found")
    return item


@router.get("/items", response_model=TrackingItemListResponse)
def get_items(
    status: TrackingStatus | None = Query(None),
    include_done: bool = Query(True),
    db: Session = Depends(get_db),
):
    items = list_tracking_items(db, status=status, include_done=include_done)
    return TrackingItemListResponse(
        items=[serialize_tracking_item(item) for item in items],
        total=len(items),
    )


@router.get("/items/{item_id}", response_model=TrackingItemResponse)
def get_item(item_id: int, db: Session = Depends(get_db)):
    return serialize_tracking_item(_get_item_or_404(db, item_id))


@router.post("/items", response_model=TrackingItemResponse, status_code=201)
def create_item(
    data: TrackingItemCreate,
    db: Session = Depends(get_db),
    _: UserInfo = Depends(require_admin),
):
    item = create_tracking_item(db, data)
    return serialize_tracking_item(item)


@router.patch("/items/{item_id}", response_model=TrackingItemResponse)
def patch_item(
    item_id: int,
    data: TrackingItemUpdate,
    db: Session = Depends(get_db),
    _: UserInfo = Depends(require_admin),
):
    item = _get_item_or_404(db, item_id)
    try:
        updated = update_tracking_item(db, item, data)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_tracking_item(updated)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    _: UserInfo = Depends(require_admin),
):
    item = _get_item_or_404(db, item_id)
    db.delete(item)
    db.commit()
    return None


@router.post("/items/{item_id}/complete", response_model=TrackingItemResponse)
def complete_item(
    item_id: int,
    db: Session = Depends(get_db),
    _: UserInfo = Depends(require_admin),
):
    item = _get_item_or_404(db, item_id)
    return serialize_tracking_item(complete_tracking_item(db, item))


@router.post("/items/{item_id}/reopen", response_model=TrackingItemResponse)
def reopen_item(
    item_id: int,
    db: Session = Depends(get_db),
    _: UserInfo = Depends(require_admin),
):
    item = _get_item_or_404(db, item_id)
    return serialize_tracking_item(reopen_tracking_item(db, item))


@router.post("/items/{item_id}/plans", response_model=TrackingItemResponse)
def link_plans(
    item_id: int,
    data: LinkPlansRequest,
    db: Session = Depends(get_db),
    _: UserInfo = Depends(require_admin),
):
    item = _get_item_or_404(db, item_id)
    existing_ids = {link.plan_record_id for link in item.linked_plans}
    for pid in data.plan_record_ids:
        if db.query(PlanRecord).filter(PlanRecord.id == pid).first() is None:
            raise HTTPException(status_code=422, detail=f"plan_record_id {pid} not found")
    for pid in data.plan_record_ids:
        if pid not in existing_ids:
            db.add(TrackingItemPlanLink(tracking_item_id=item_id, plan_record_id=pid))
    db.commit()
    return serialize_tracking_item(_get_item_or_404(db, item_id))


@router.delete("/items/{item_id}/plans/{plan_record_id}", response_model=TrackingItemResponse)
def unlink_plan(
    item_id: int,
    plan_record_id: int,
    db: Session = Depends(get_db),
    _: UserInfo = Depends(require_admin),
):
    item = _get_item_or_404(db, item_id)
    link = (
        db.query(TrackingItemPlanLink)
        .filter(
            TrackingItemPlanLink.tracking_item_id == item_id,
            TrackingItemPlanLink.plan_record_id == plan_record_id,
        )
        .first()
    )
    if link:
        db.delete(link)
        db.commit()
    return serialize_tracking_item(_get_item_or_404(db, item_id))

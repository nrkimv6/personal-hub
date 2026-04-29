"""Tracking item API routes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth import UserInfo, require_admin
from app.database import get_db
from app.models.tracking_item import TrackingItem
from app.schemas.tracking import (
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
    item = db.query(TrackingItem).filter(TrackingItem.id == item_id).first()
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

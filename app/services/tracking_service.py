"""Business logic for Tracking items."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.tracking_item import TrackingItem
from app.schemas.tracking import TrackingItemCreate, TrackingItemResponse, TrackingItemUpdate, TrackingStatus


def calculate_tracking_status(item: TrackingItem, now: datetime | None = None) -> TrackingStatus:
    current = now or datetime.now()
    if item.completed_at is not None:
        return "done"
    if item.due_at is not None and item.due_at < current:
        return "overdue"
    if item.start_at is not None and item.start_at > current:
        return "upcoming"
    return "ready"


def _sort_key(item: TrackingItem):
    status = calculate_tracking_status(item)
    if status == "done":
        completed = item.completed_at or datetime.min
        return (1, 0, datetime.max - (completed - datetime.min))

    status_rank = {"overdue": 0, "ready": 1, "upcoming": 2}[status]
    next_date = item.due_at or item.start_at or datetime.max
    return (0, status_rank, next_date)


def serialize_tracking_item(item: TrackingItem) -> TrackingItemResponse:
    return TrackingItemResponse(
        id=item.id,
        title=item.title,
        description=item.description,
        start_at=item.start_at,
        due_at=item.due_at,
        completed_at=item.completed_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
        status=calculate_tracking_status(item),
    )


def list_tracking_items(
    db: Session,
    *,
    status: TrackingStatus | None = None,
    include_done: bool = True,
) -> list[TrackingItem]:
    items = db.query(TrackingItem).all()
    filtered = []
    for item in items:
        item_status = calculate_tracking_status(item)
        if not include_done and item_status == "done":
            continue
        if status is not None and item_status != status:
            continue
        filtered.append(item)
    return sorted(filtered, key=_sort_key)


def create_tracking_item(db: Session, data: TrackingItemCreate) -> TrackingItem:
    item = TrackingItem(
        title=data.title,
        description=data.description,
        start_at=data.start_at,
        due_at=data.due_at,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_tracking_item(db: Session, item: TrackingItem, data: TrackingItemUpdate) -> TrackingItem:
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)
    if item.start_at is None and item.due_at is None:
        raise ValueError("start_at 또는 due_at 중 하나 이상이 필요합니다.")
    item.updated_at = datetime.now()
    db.commit()
    db.refresh(item)
    return item


def complete_tracking_item(db: Session, item: TrackingItem) -> TrackingItem:
    item.completed_at = datetime.now()
    item.updated_at = datetime.now()
    db.commit()
    db.refresh(item)
    return item


def reopen_tracking_item(db: Session, item: TrackingItem) -> TrackingItem:
    item.completed_at = None
    item.updated_at = datetime.now()
    db.commit()
    db.refresh(item)
    return item

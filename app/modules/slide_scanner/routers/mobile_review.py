"""Mobile review endpoints for slide scanner pre-gate pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.slide_scanner.config import parse_mobile_device_aliases, settings
from app.modules.slide_scanner.database import SessionLocal, get_db
from app.modules.slide_scanner.services.mobile_delete import process_remote_delete_for_item
from app.modules.slide_scanner.services.mobile_handoff import handoff_item_to_slides
from app.modules.slide_scanner.services.task_store import create_task

router = APIRouter(prefix="/mobile-review", tags=["slide-scanner"])
_APPROVAL_STATUSES = {"PENDING", "APPROVED", "REJECTED"}


class RejectRequest(BaseModel):
    reason: str = Field(default="Rejected by reviewer", min_length=1, max_length=500)


def _fetch_mobile_item_or_404(db: Session, item_id: int):
    row = db.execute(
        text("SELECT * FROM mobile_ingest_items WHERE id = :id"),
        {"id": item_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Mobile ingest item not found")
    return row


def _normalize_approval_status_filter(raw_values: list[str] | None) -> list[str]:
    if not raw_values:
        return ["PENDING", "APPROVED"]

    normalized: list[str] = []
    for raw in raw_values:
        for candidate in raw.split(","):
            value = candidate.strip().upper()
            if not value:
                continue
            if value not in _APPROVAL_STATUSES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported approval_status: {value}",
                )
            if value not in normalized:
                normalized.append(value)

    if not normalized:
        raise HTTPException(status_code=400, detail="approval_status filter is empty")
    return normalized


def _derive_action_flags(
    *,
    approval_status: str,
    remote_delete_status: str,
    handoff_status: str,
    slide_id: int | None,
) -> dict[str, bool]:
    can_approve = approval_status == "PENDING"
    can_remote_delete = (
        approval_status == "APPROVED"
        and remote_delete_status != "DONE"
        and handoff_status != "DONE"
    )
    can_handoff = (
        approval_status == "APPROVED"
        and remote_delete_status == "DONE"
        and handoff_status != "DONE"
    )
    can_open_editor = handoff_status == "DONE" and slide_id is not None
    return {
        "can_approve": can_approve,
        "can_remote_delete": can_remote_delete,
        "can_handoff": can_handoff,
        "can_open_editor": can_open_editor,
    }


def _build_state_snapshot(row) -> dict[str, Any]:
    slide_id = int(row.slide_id) if row.slide_id is not None else None
    payload: dict[str, Any] = {
        "approval_status": row.approval_status,
        "remote_delete_status": row.remote_delete_status,
        "handoff_status": row.handoff_status,
        "slide_id": slide_id,
    }
    payload.update(
        _derive_action_flags(
            approval_status=row.approval_status,
            remote_delete_status=row.remote_delete_status,
            handoff_status=row.handoff_status,
            slide_id=slide_id,
        )
    )
    return payload


def _fetch_mobile_item_state(db: Session, item_id: int):
    row = db.execute(
        text(
            """
            SELECT
                id,
                approval_status,
                remote_delete_status,
                handoff_status,
                slide_id
            FROM mobile_ingest_items
            WHERE id = :item_id
            """
        ),
        {"item_id": item_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Mobile ingest item not found")
    return row


@router.get("/items")
def get_mobile_review_items(
    device_id: str | None = None,
    approval_status: list[str] | None = Query(default=None),
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if skip < 0:
        raise HTTPException(status_code=400, detail="skip must be >= 0")
    if limit <= 0 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")

    aliases = parse_mobile_device_aliases(settings.MOBILE_DEVICE_ALIAS_JSON)
    approval_filter = _normalize_approval_status_filter(approval_status)
    params: dict[str, Any] = {"skip": skip, "limit": limit}
    where_clauses: list[str] = []

    approval_placeholders: list[str] = []
    for index, status in enumerate(approval_filter):
        key = f"approval_status_{index}"
        params[key] = status
        approval_placeholders.append(f":{key}")
    where_clauses.append(f"approval_status IN ({', '.join(approval_placeholders)})")

    if device_id:
        where_clauses.append("device_id = :device_id")
        params["device_id"] = device_id
    where_clause = "WHERE " + " AND ".join(where_clauses)

    total = (
        db.execute(
            text(f"SELECT COUNT(*) FROM mobile_ingest_items {where_clause}"),
            params,
        ).scalar()
        or 0
    )

    rows = db.execute(
        text(
            f"""
            SELECT
                id,
                device_id,
                device_serial,
                original_filename,
                source_uri,
                pc_inbox_path,
                captured_at_utc,
                approval_status,
                remote_delete_status,
                handoff_status,
                local_cleanup_status,
                slide_id,
                error_message,
                created_at,
                updated_at
            FROM mobile_ingest_items
            {where_clause}
            ORDER BY captured_at_utc DESC, id DESC
            LIMIT :limit OFFSET :skip
            """
        ),
        params,
    ).fetchall()

    items = []
    for row in rows:
        item = {
            "id": row.id,
            "device_id": row.device_id,
            "device_serial": row.device_serial,
            "device_alias": aliases.get(row.device_serial),
            "original_filename": row.original_filename,
            "source_uri": row.source_uri,
            "pc_inbox_path": row.pc_inbox_path,
            "captured_at_utc": row.captured_at_utc,
            "approval_status": row.approval_status,
            "remote_delete_status": row.remote_delete_status,
            "handoff_status": row.handoff_status,
            "local_cleanup_status": row.local_cleanup_status,
            "slide_id": int(row.slide_id) if row.slide_id is not None else None,
            "error_message": row.error_message,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "image_url": f"/api/v1/ss/mobile-review/{row.id}/image",
        }
        item.update(
            _derive_action_flags(
                approval_status=row.approval_status,
                remote_delete_status=row.remote_delete_status,
                handoff_status=row.handoff_status,
                slide_id=int(row.slide_id) if row.slide_id is not None else None,
            )
        )
        items.append(item)

    return {
        "items": items,
        "skip": skip,
        "limit": limit,
        "total": int(total),
        "has_more": skip + len(items) < int(total),
    }


@router.get("/{item_id}/image")
def get_mobile_review_image(item_id: int, db: Session = Depends(get_db)):
    row = _fetch_mobile_item_or_404(db, item_id)
    image_path = Path(str(row.pc_inbox_path))
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Inbox image file not found")
    return FileResponse(path=str(image_path), media_type="image/jpeg")


@router.post("/{item_id}/approve")
def approve_mobile_review_item(item_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _fetch_mobile_item_or_404(db, item_id)
    if row.approval_status != "PENDING":
        raise HTTPException(status_code=409, detail="Only PENDING items can be approved")
    db.execute(
        text(
            """
            UPDATE mobile_ingest_items
            SET approval_status = 'APPROVED',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :item_id
            """
        ),
        {"item_id": item_id},
    )
    db.commit()
    state = _fetch_mobile_item_state(db, item_id)
    payload = {"id": item_id}
    payload.update(_build_state_snapshot(state))
    return payload


@router.post("/{item_id}/reject")
def reject_mobile_review_item(
    item_id: int,
    request: RejectRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    row = _fetch_mobile_item_or_404(db, item_id)
    if row.approval_status != "PENDING":
        raise HTTPException(status_code=409, detail="Only PENDING items can be rejected")
    db.execute(
        text(
            """
            UPDATE mobile_ingest_items
            SET approval_status = 'REJECTED',
                error_message = :reason,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :item_id
            """
        ),
        {
            "item_id": item_id,
            "reason": request.reason.strip(),
        },
    )
    db.commit()
    state = _fetch_mobile_item_state(db, item_id)
    payload = {
        "id": item_id,
        "reason": request.reason.strip(),
    }
    payload.update(_build_state_snapshot(state))
    return payload


def _require_approved_for_delete(row) -> None:
    if row.approval_status != "APPROVED":
        raise HTTPException(
            status_code=409,
            detail="Mobile item must be APPROVED before remote delete",
        )


@router.post("/{item_id}/remote-delete")
def remote_delete_mobile_item(item_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _fetch_mobile_item_or_404(db, item_id)
    _require_approved_for_delete(row)

    result = process_remote_delete_for_item(
        db=db,
        item_id=item_id,
        adb_path=settings.ADB_PATH,
        allowed_roots=settings.MOBILE_REMOTE_ROOTS,
    )
    state = _fetch_mobile_item_state(db, item_id)
    payload = dict(result)
    payload.update(_build_state_snapshot(state))
    return payload


@router.post("/{item_id}/remote-delete/tasks", status_code=202)
def start_remote_delete_mobile_item_task(item_id: int, background_tasks: BackgroundTasks):
    def runner() -> dict:
        db = SessionLocal()
        try:
            return remote_delete_mobile_item(item_id, db)
        finally:
            db.close()

    return create_task("slide-mobile-remote-delete", background_tasks, runner)


@router.post("/{item_id}/remote-delete/retry")
def retry_remote_delete_mobile_item(item_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _fetch_mobile_item_or_404(db, item_id)
    _require_approved_for_delete(row)

    result = process_remote_delete_for_item(
        db=db,
        item_id=item_id,
        adb_path=settings.ADB_PATH,
        allowed_roots=settings.MOBILE_REMOTE_ROOTS,
    )
    state = _fetch_mobile_item_state(db, item_id)
    payload = dict(result)
    payload.update(_build_state_snapshot(state))
    return payload


@router.post("/{item_id}/remote-delete/retry/tasks", status_code=202)
def start_retry_remote_delete_mobile_item_task(item_id: int, background_tasks: BackgroundTasks):
    def runner() -> dict:
        db = SessionLocal()
        try:
            return retry_remote_delete_mobile_item(item_id, db)
        finally:
            db.close()

    return create_task("slide-mobile-remote-delete-retry", background_tasks, runner)


@router.post("/{item_id}/handoff")
def handoff_mobile_item(item_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _fetch_mobile_item_or_404(db, item_id)
    if row.approval_status != "APPROVED" or row.remote_delete_status != "DONE":
        raise HTTPException(
            status_code=409,
            detail="Handoff requires approval_status=APPROVED and remote_delete_status=DONE",
        )

    try:
        slide_id = handoff_item_to_slides(db, item_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    state = _fetch_mobile_item_state(db, item_id)
    payload = {
        "item_id": item_id,
        "slide_id": slide_id,
        "slide_url": f"/api/v1/ss/slides/{slide_id}",
    }
    payload.update(_build_state_snapshot(state))
    return payload

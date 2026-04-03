"""Mobile review endpoints for slide scanner pre-gate pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.slide_scanner.config import parse_mobile_device_aliases, settings
from app.modules.slide_scanner.database import get_db
from app.modules.slide_scanner.services.mobile_delete import process_remote_delete_for_item
from app.modules.slide_scanner.services.mobile_handoff import handoff_item_to_slides

router = APIRouter(prefix="/mobile-review", tags=["slide-scanner"])


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


@router.get("/items")
def get_mobile_review_items(
    device_id: str | None = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if skip < 0:
        raise HTTPException(status_code=400, detail="skip must be >= 0")
    if limit <= 0 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")

    aliases = parse_mobile_device_aliases(settings.MOBILE_DEVICE_ALIAS_JSON)
    where_clause = "WHERE approval_status = 'PENDING'"
    params: dict[str, Any] = {"skip": skip, "limit": limit}
    if device_id:
        where_clause += " AND device_id = :device_id"
        params["device_id"] = device_id

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
            "error_message": row.error_message,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "image_url": f"/api/v1/ss/mobile-review/{row.id}/image",
        }
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
    return {
        "id": item_id,
        "approval_status": "APPROVED",
    }


@router.post("/{item_id}/reject")
def reject_mobile_review_item(
    item_id: int,
    payload: RejectRequest,
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
            "reason": payload.reason.strip(),
        },
    )
    db.commit()
    return {
        "id": item_id,
        "approval_status": "REJECTED",
        "reason": payload.reason.strip(),
    }


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
    return result


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
    return result


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

    return {
        "item_id": item_id,
        "slide_id": slide_id,
        "slide_url": f"/api/v1/ss/slides/{slide_id}",
    }

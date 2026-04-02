"""Gallery/list endpoints for slide scanner."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.slide_scanner.database import get_db

router = APIRouter(prefix="/slides", tags=["slide-scanner"])

VALID_STATUS = {"PENDING", "REVIEWED", "DONE"}


def _load_filters(value: str | None) -> dict[str, object] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None

    try:
        contrast = float(parsed.get("contrast", 1.0))
    except (TypeError, ValueError):
        contrast = 1.0

    normalized = {
        "white_balance": bool(parsed.get("white_balance", False)),
        "contrast": max(0.5, min(2.0, contrast)),
        "document_mode": bool(parsed.get("document_mode", False)),
    }
    if (
        not normalized["white_balance"]
        and not normalized["document_mode"]
        and abs(float(normalized["contrast"]) - 1.0) < 1e-6
    ):
        return None
    return normalized


@router.get("")
def get_slides(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=24, ge=1, le=200),
    status: str | None = None,
    db: Session = Depends(get_db),
):
    status_filter = status.upper() if status else None
    if status_filter == "ALL":
        status_filter = None
    if status_filter and status_filter not in VALID_STATUS:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    where_clause = "WHERE 1=1"
    params: dict[str, object] = {"skip": skip, "limit": limit}

    if status_filter:
        where_clause += " AND status = :status"
        params["status"] = status_filter

    total = (
        db.execute(text(f"SELECT COUNT(*) FROM slides {where_clause}"), params).scalar()  # noqa: S608
        or 0
    )

    rows = db.execute(
        text(
            f"""
            SELECT
                id, file_name, file_path, result_path, status,
                aspect_ratio, filters_applied,
                captured_at, source_app, is_archived, created_at, updated_at
            FROM slides
            {where_clause}
            ORDER BY (captured_at IS NULL) ASC, captured_at DESC, id DESC
            LIMIT :limit OFFSET :skip
            """
        ),
        params,
    ).fetchall()

    slides = [
        {
            "id": row.id,
            "file_name": row.file_name,
            "file_path": row.file_path,
            "result_path": row.result_path,
            "status": row.status,
            "aspect_ratio": row.aspect_ratio,
            "filters_applied": _load_filters(row.filters_applied),
            "captured_at": row.captured_at,
            "source_app": row.source_app,
            "is_archived": bool(row.is_archived),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "thumbnail_url": f"/api/v1/ss/slides/{row.id}/thumbnail",
        }
        for row in rows
    ]

    return {
        "slides": slides,
        "skip": skip,
        "limit": limit,
        "total": int(total),
        "has_more": skip + len(slides) < int(total),
    }


@router.get("/{slide_id}/thumbnail")
def get_slide_thumbnail(slide_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT thumbnail FROM slides WHERE id = :id"),
        {"id": slide_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Slide not found")
    if not row.thumbnail:
        raise HTTPException(status_code=404, detail="Thumbnail not available")

    return Response(content=bytes(row.thumbnail), media_type="image/jpeg")

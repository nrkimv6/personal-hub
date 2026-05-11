"""Batch transform endpoint for slide scanner."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.database import SessionLocal, get_db
from app.modules.slide_scanner.services.rectifier_client import SlideFilterOptions, rectifier_client
from app.modules.slide_scanner.services.task_store import create_task

router = APIRouter(prefix="/slides", tags=["slide-scanner"])


class FilterPayload(BaseModel):
    white_balance: bool = False
    contrast: float = 1.0
    document_mode: bool = False


class BatchTransformRequest(BaseModel):
    ids: list[int] = Field(..., min_length=1)
    aspect_ratio: str | None = None
    filters: FilterPayload | None = None


def _build_in_clause(ids: list[int]) -> tuple[str, dict[str, int]]:
    placeholders = []
    params: dict[str, int] = {}
    for index, value in enumerate(ids):
        key = f"id_{index}"
        placeholders.append(f":{key}")
        params[key] = value
    return ", ".join(placeholders), params


def _row_points(row) -> list[tuple[float, float]] | None:
    values = (
        row.pt_tl_x,
        row.pt_tl_y,
        row.pt_tr_x,
        row.pt_tr_y,
        row.pt_br_x,
        row.pt_br_y,
        row.pt_bl_x,
        row.pt_bl_y,
    )
    if any(value is None for value in values):
        return None
    return [
        (float(row.pt_tl_x), float(row.pt_tl_y)),
        (float(row.pt_tr_x), float(row.pt_tr_y)),
        (float(row.pt_br_x), float(row.pt_br_y)),
        (float(row.pt_bl_x), float(row.pt_bl_y)),
    ]


def _normalize_aspect_ratio(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized in {"", "AUTO"}:
        return None
    if normalized in {"16:9", "4:3"}:
        return normalized
    raise ValueError("Invalid aspect_ratio. Use AUTO, 16:9, or 4:3")


def _normalize_filters(payload: FilterPayload | None) -> SlideFilterOptions | None:
    if payload is None:
        return None

    contrast = float(payload.contrast)
    if contrast < 0.5 or contrast > 2.0:
        raise ValueError("Invalid filters.contrast. Use range 0.5 ~ 2.0")

    normalized: SlideFilterOptions = {
        "white_balance": bool(payload.white_balance),
        "contrast": contrast,
        "document_mode": bool(payload.document_mode),
    }
    if (
        not normalized["white_balance"]
        and not normalized["document_mode"]
        and abs(normalized["contrast"] - 1.0) < 1e-6
    ):
        return None
    return normalized


@router.post("/batch-transform")
def batch_transform(request: BatchTransformRequest, db: Session = Depends(get_db)):
    ids = list(dict.fromkeys(request.ids))
    try:
        normalized_aspect_ratio = _normalize_aspect_ratio(request.aspect_ratio)
        normalized_filters = _normalize_filters(request.filters)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    in_clause, in_params = _build_in_clause(ids)

    rows = db.execute(
        text(
            f"""
            SELECT
                id, file_path, result_path, status, is_archived,
                pt_tl_x, pt_tl_y, pt_tr_x, pt_tr_y,
                pt_br_x, pt_br_y, pt_bl_x, pt_bl_y
            FROM slides
            WHERE id IN ({in_clause})
            """
        ),
        in_params,
    ).fetchall()
    row_map = {int(row.id): row for row in rows}

    done = 0
    failed = 0
    skipped = 0
    failures: list[dict[str, Any]] = []

    for slide_id in ids:
        row = row_map.get(slide_id)
        if not row:
            failed += 1
            failures.append({"id": slide_id, "reason": "not_found"})
            continue
        if int(row.is_archived or 0) == 1:
            skipped += 1
            failures.append({"id": slide_id, "reason": "archived"})
            continue

        source_path = Path(row.file_path)
        if not source_path.exists():
            failed += 1
            failures.append({"id": slide_id, "reason": "original_missing"})
            continue

        points = _row_points(row)
        if not points:
            failed += 1
            failures.append({"id": slide_id, "reason": "points_missing"})
            continue

        output_name = f"{slide_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        output_path = settings.OUTPUT_DIR / output_name

        try:
            transformed = rectifier_client.transform(
                image_path=source_path,
                points=points,
                output_path=output_path,
                aspect_ratio=normalized_aspect_ratio,
                filters=normalized_filters,
            )
            db.execute(
                text(
                    """
                    UPDATE slides
                    SET status = 'DONE',
                        result_path = :result_path,
                        aspect_ratio = :aspect_ratio,
                        filters_applied = :filters_applied,
                        extracted_text = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                    """
                ),
                {
                    "id": slide_id,
                    "result_path": str(transformed),
                    "aspect_ratio": normalized_aspect_ratio,
                    "filters_applied": (
                        json.dumps(normalized_filters, ensure_ascii=False) if normalized_filters else None
                    ),
                },
            )
            db.commit()
            done += 1
        except Exception as exc:
            db.rollback()
            failed += 1
            failures.append({"id": slide_id, "reason": str(exc)})

    return {
        "requested": len(ids),
        "done": done,
        "failed": failed,
        "skipped": skipped,
        "failures": failures[:50],
    }


@router.post("/batch-transform/tasks", status_code=202)
def start_batch_transform_task(request: BatchTransformRequest, background_tasks: BackgroundTasks):
    def runner() -> dict:
        db = SessionLocal()
        try:
            return batch_transform(request, db)
        finally:
            db.close()

    return create_task("slide-batch-transform", background_tasks, runner)

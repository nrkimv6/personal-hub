"""PDF export endpoints for slide scanner."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.database import get_db
from app.modules.slide_scanner.services.rectifier_client import rectifier_client

router = APIRouter(prefix="/export", tags=["slide-scanner"])


class PdfExportRequest(BaseModel):
    ids: list[int] = Field(..., min_length=1)
    filename: str | None = None


def _build_in_clause(ids: list[int]) -> tuple[str, dict[str, int]]:
    placeholders = []
    params: dict[str, int] = {}
    for index, value in enumerate(ids):
        key = f"id_{index}"
        placeholders.append(f":{key}")
        params[key] = value
    return ", ".join(placeholders), params


def _normalize_filename(value: str | None) -> str:
    fallback = f"slides_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    if value is None:
        return fallback

    stem = Path(value.strip()).stem
    if not stem:
        return fallback

    safe_stem = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", stem).strip("._")
    if not safe_stem:
        return fallback
    return f"{safe_stem}.pdf"


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


@router.post("/pdf")
def export_pdf(
    payload: PdfExportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    ids = list(dict.fromkeys(payload.ids))
    in_clause, in_params = _build_in_clause(ids)

    rows = db.execute(
        text(
            f"""
            SELECT id, captured_at, result_path
            FROM slides
            WHERE id IN ({in_clause})
              AND is_archived = 0
            """
        ),
        in_params,
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="No matching slides found")

    row_map = {int(row.id): row for row in rows}
    ordered_rows = [
        row_map[slide_id]
        for slide_id in ids
        if slide_id in row_map
    ]
    ordered_rows.sort(
        key=lambda row: (
            row.captured_at is None,
            row.captured_at or "",
            int(row.id),
        )
    )

    image_paths: list[Path] = []
    for row in ordered_rows:
        if not row.result_path:
            continue
        result_path = Path(row.result_path)
        if result_path.exists():
            image_paths.append(result_path)

    if not image_paths:
        raise HTTPException(
            status_code=400,
            detail="No transformed result images available for PDF export",
        )

    output_name = _normalize_filename(payload.filename)
    export_dir = settings.OUTPUT_DIR / "_exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    output_path = export_dir / f"{uuid4().hex}_{output_name}"

    try:
        pdf_path = rectifier_client.export_pdf(
            image_paths=image_paths,
            output_path=output_path,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"PDF export failed: {exc}") from exc

    background_tasks.add_task(_safe_unlink, pdf_path)
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=output_name,
    )

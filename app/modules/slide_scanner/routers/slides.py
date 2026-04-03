"""Core slide scanner APIs."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.database import get_db
from app.modules.slide_scanner.services.rectifier_client import (
    DetectMeta,
    SlideFilterOptions,
    rectifier_client,
)

router = APIRouter(prefix="/slides", tags=["slide-scanner"])


class PointPayload(BaseModel):
    x: float
    y: float


class FilterPayload(BaseModel):
    white_balance: bool = False
    contrast: float = 1.0
    document_mode: bool = False


class TransformRequest(BaseModel):
    points: list[PointPayload]
    aspect_ratio: str | None = None
    filters: FilterPayload | None = None


class ReviewRequest(BaseModel):
    points: list[PointPayload]


class OcrRequest(BaseModel):
    languages: list[str] | None = None


class SlideUpdateRequest(BaseModel):
    tag: str | None = None


def _points_to_params(points: list[tuple[float, float]]) -> dict[str, float]:
    if len(points) != 4:
        raise ValueError("Exactly four points are required")
    return {
        "pt_tl_x": points[0][0],
        "pt_tl_y": points[0][1],
        "pt_tr_x": points[1][0],
        "pt_tr_y": points[1][1],
        "pt_br_x": points[2][0],
        "pt_br_y": points[2][1],
        "pt_bl_x": points[3][0],
        "pt_bl_y": points[3][1],
    }


def _detect_meta_to_params(meta: DetectMeta | None) -> dict[str, str | float | None]:
    if not meta:
        return {
            "detect_engine": None,
            "detect_confidence": None,
            "detect_fallback_reason": None,
        }
    return {
        "detect_engine": str(meta.get("selected_engine") or "").strip() or None,
        "detect_confidence": (
            float(meta["confidence"]) if meta.get("confidence") is not None else None
        ),
        "detect_fallback_reason": (
            str(meta.get("fallback_reason")).strip()
            if meta.get("fallback_reason") is not None
            else None
        ),
    }


def _normalize_detect_meta(meta: DetectMeta | None) -> dict[str, str | float | None] | None:
    if not meta:
        return None
    return {
        "requested_engine": str(meta.get("requested_engine") or "").strip() or None,
        "selected_engine": str(meta.get("selected_engine") or "").strip() or None,
        "confidence": (float(meta["confidence"]) if meta.get("confidence") is not None else None),
        "fallback_reason": (
            str(meta.get("fallback_reason")).strip()
            if meta.get("fallback_reason") is not None
            else None
        ),
        "selection_reason": (
            str(meta.get("selection_reason")).strip()
            if meta.get("selection_reason") is not None
            else None
        ),
    }


def _row_to_points(row) -> list[dict[str, float]]:
    if (
        row.pt_tl_x is None
        or row.pt_tl_y is None
        or row.pt_tr_x is None
        or row.pt_tr_y is None
        or row.pt_br_x is None
        or row.pt_br_y is None
        or row.pt_bl_x is None
        or row.pt_bl_y is None
    ):
        return []

    return [
        {"x": float(row.pt_tl_x), "y": float(row.pt_tl_y)},
        {"x": float(row.pt_tr_x), "y": float(row.pt_tr_y)},
        {"x": float(row.pt_br_x), "y": float(row.pt_br_y)},
        {"x": float(row.pt_bl_x), "y": float(row.pt_bl_y)},
    ]


def _row_to_detect_meta(row) -> dict[str, str | float | None] | None:
    if (
        row.detect_engine is None
        and row.detect_confidence is None
        and row.detect_fallback_reason is None
    ):
        return None
    return {
        "selected_engine": row.detect_engine,
        "confidence": (float(row.detect_confidence) if row.detect_confidence is not None else None),
        "fallback_reason": row.detect_fallback_reason,
    }


def _build_thumbnail_bytes(image_path: Path) -> bytes:
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        rgb.thumbnail(settings.THUMBNAIL_SIZE)
        buffer = BytesIO()
        rgb.save(buffer, format="JPEG", quality=settings.THUMBNAIL_QUALITY)
        return buffer.getvalue()


def _as_base64(binary: bytes | None) -> str | None:
    if not binary:
        return None
    return base64.b64encode(binary).decode("ascii")


def _load_slide_or_404(db: Session, slide_id: int):
    row = db.execute(text("SELECT * FROM slides WHERE id = :id"), {"id": slide_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Slide not found")
    return row


def _normalize_aspect_ratio(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip().upper()
    if normalized in {"", "AUTO"}:
        return None
    if normalized in {"16:9", "4:3"}:
        return normalized
    raise HTTPException(status_code=400, detail="Invalid aspect_ratio. Use AUTO, 16:9, or 4:3")


def _normalize_filters(payload: FilterPayload | None) -> SlideFilterOptions | None:
    if payload is None:
        return None

    contrast = float(payload.contrast)
    if contrast < 0.5 or contrast > 2.0:
        raise HTTPException(status_code=400, detail="Invalid filters.contrast. Use range 0.5 ~ 2.0")

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


def _normalize_tag(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > 64:
        raise HTTPException(status_code=400, detail="Tag is too long. Maximum length is 64.")
    return normalized


def _load_filters(value: str | None) -> SlideFilterOptions | None:
    if not value:
        return None

    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None

    try:
        contrast = float(raw.get("contrast", 1.0))
    except (TypeError, ValueError):
        contrast = 1.0
    contrast = max(0.5, min(2.0, contrast))

    normalized: SlideFilterOptions = {
        "white_balance": bool(raw.get("white_balance", False)),
        "contrast": contrast,
        "document_mode": bool(raw.get("document_mode", False)),
    }
    if (
        not normalized["white_balance"]
        and not normalized["document_mode"]
        and abs(normalized["contrast"] - 1.0) < 1e-6
    ):
        return None
    return normalized


def _find_inherited_points(db: Session, row) -> list[dict[str, float]] | None:
    base_sql = """
        SELECT
            pt_tl_x, pt_tl_y, pt_tr_x, pt_tr_y,
            pt_br_x, pt_br_y, pt_bl_x, pt_bl_y
        FROM slides
        WHERE id != :id
          AND status IN ('REVIEWED', 'DONE')
          AND pt_tl_x IS NOT NULL AND pt_tl_y IS NOT NULL
          AND pt_tr_x IS NOT NULL AND pt_tr_y IS NOT NULL
          AND pt_br_x IS NOT NULL AND pt_br_y IS NOT NULL
          AND pt_bl_x IS NOT NULL AND pt_bl_y IS NOT NULL
    """

    inherited = None
    if row.captured_at:
        inherited = db.execute(
            text(
                base_sql
                + """
                  AND captured_at IS NOT NULL
                  AND captured_at < :captured_at
                ORDER BY captured_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"id": row.id, "captured_at": row.captured_at},
        ).fetchone()

    if not inherited:
        inherited = db.execute(
            text(
                base_sql
                + """
                  AND id < :id
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"id": row.id},
        ).fetchone()

    if not inherited:
        return None
    return _row_to_points(inherited) or None


@router.post("/upload")
async def upload_slide(
    file: UploadFile = File(...),
    source_app: str | None = Form(default=None),
    captured_at: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are supported")

    suffix = Path(file.filename or "").suffix.lower() or ".jpg"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stored_name = f"{timestamp}_{uuid4().hex[:8]}{suffix}"
    stored_path = settings.ORIGINALS_DIR / stored_name

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    stored_path.write_bytes(content)

    try:
        detected = rectifier_client.detect_with_meta(stored_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Corner detection failed: {exc}") from exc

    thumbnail = _build_thumbnail_bytes(stored_path)
    point_params = _points_to_params(detected["points"])
    detect_meta = _normalize_detect_meta(detected["meta"])

    db.execute(
        text(
            """
            INSERT INTO slides (
                file_name, file_path, status,
                pt_tl_x, pt_tl_y, pt_tr_x, pt_tr_y, pt_br_x, pt_br_y, pt_bl_x, pt_bl_y,
                detect_engine, detect_confidence, detect_fallback_reason,
                captured_at, source_app, thumbnail, is_archived
            ) VALUES (
                :file_name, :file_path, 'REVIEWED',
                :pt_tl_x, :pt_tl_y, :pt_tr_x, :pt_tr_y, :pt_br_x, :pt_br_y, :pt_bl_x, :pt_bl_y,
                :detect_engine, :detect_confidence, :detect_fallback_reason,
                :captured_at, :source_app, :thumbnail, 0
            )
            """
        ),
        {
            "file_name": file.filename or stored_name,
            "file_path": str(stored_path),
            "captured_at": captured_at,
            "source_app": source_app,
            "thumbnail": thumbnail,
            **point_params,
            **_detect_meta_to_params(detected["meta"]),
        },
    )
    slide_id = db.execute(text("SELECT last_insert_rowid()")).scalar_one()
    db.commit()

    slide = _load_slide_or_404(db, slide_id)
    return {
        "id": slide.id,
        "status": slide.status,
        "points": _row_to_points(slide),
        "detect_meta": detect_meta,
        "thumbnail_base64": _as_base64(slide.thumbnail),
    }


@router.get("/{slide_id}")
def get_slide(slide_id: int, db: Session = Depends(get_db)):
    row = _load_slide_or_404(db, slide_id)
    inherited_points = _find_inherited_points(db, row)
    return {
        "id": row.id,
        "file_name": row.file_name,
        "status": row.status,
        "tag": row.tag,
        "captured_at": row.captured_at,
        "source_app": row.source_app,
        "aspect_ratio": row.aspect_ratio,
        "filters_applied": _load_filters(row.filters_applied),
        "extracted_text": row.extracted_text,
        "points": _row_to_points(row),
        "detect_meta": _row_to_detect_meta(row),
        "inherited_points": inherited_points,
        "has_result": bool(row.result_path),
        "thumbnail_base64": _as_base64(row.thumbnail),
    }


@router.get("/{slide_id}/image")
def get_slide_image(slide_id: int, db: Session = Depends(get_db)):
    row = _load_slide_or_404(db, slide_id)
    image_path = Path(row.file_path)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Original image file not found")
    return FileResponse(path=str(image_path), media_type="image/jpeg")


@router.post("/{slide_id}/transform")
def transform_slide(slide_id: int, payload: TransformRequest, db: Session = Depends(get_db)):
    row = _load_slide_or_404(db, slide_id)
    source_path = Path(row.file_path)
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Original image file not found")

    normalized_aspect_ratio = _normalize_aspect_ratio(payload.aspect_ratio)
    normalized_filters = _normalize_filters(payload.filters)
    point_tuples = [(p.x, p.y) for p in payload.points]
    output_name = f"{slide_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    output_path = settings.OUTPUT_DIR / output_name

    try:
        transformed = rectifier_client.transform(
            image_path=source_path,
            points=point_tuples,
            output_path=output_path,
            aspect_ratio=normalized_aspect_ratio,
            filters=normalized_filters,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Transform failed: {exc}") from exc

    point_params = _points_to_params(point_tuples)
    db.execute(
        text(
            """
            UPDATE slides
            SET status = 'DONE',
                result_path = :result_path,
                aspect_ratio = :aspect_ratio,
                filters_applied = :filters_applied,
                extracted_text = NULL,
                pt_tl_x = :pt_tl_x, pt_tl_y = :pt_tl_y,
                pt_tr_x = :pt_tr_x, pt_tr_y = :pt_tr_y,
                pt_br_x = :pt_br_x, pt_br_y = :pt_br_y,
                pt_bl_x = :pt_bl_x, pt_bl_y = :pt_bl_y,
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
            **point_params,
        },
    )
    db.commit()

    return {
        "id": slide_id,
        "status": "DONE",
        "aspect_ratio": normalized_aspect_ratio,
        "filters_applied": normalized_filters,
        "result_path": str(transformed),
        "result_url": f"/api/v1/ss/slides/{slide_id}/result",
    }


@router.post("/{slide_id}/ocr")
def extract_slide_text(slide_id: int, payload: OcrRequest | None = None, db: Session = Depends(get_db)):
    row = _load_slide_or_404(db, slide_id)
    if not row.result_path:
        raise HTTPException(status_code=400, detail="Transform result is required before OCR")

    result_path = Path(row.result_path)
    if not result_path.exists():
        raise HTTPException(status_code=404, detail="Result image file not found")

    languages = payload.languages if payload else None
    try:
        extracted_text = rectifier_client.extract_text(result_path, languages)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"OCR failed: {exc}") from exc

    db.execute(
        text(
            """
            UPDATE slides
            SET extracted_text = :extracted_text,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
            """
        ),
        {
            "id": slide_id,
            "extracted_text": extracted_text,
        },
    )
    db.commit()

    return {"id": slide_id, "extracted_text": extracted_text}


@router.post("/{slide_id}/review")
def review_slide(slide_id: int, payload: ReviewRequest, db: Session = Depends(get_db)):
    _load_slide_or_404(db, slide_id)
    point_tuples = [(p.x, p.y) for p in payload.points]
    point_params = _points_to_params(point_tuples)

    db.execute(
        text(
            """
            UPDATE slides
            SET status = 'REVIEWED',
                pt_tl_x = :pt_tl_x, pt_tl_y = :pt_tl_y,
                pt_tr_x = :pt_tr_x, pt_tr_y = :pt_tr_y,
                pt_br_x = :pt_br_x, pt_br_y = :pt_br_y,
                pt_bl_x = :pt_bl_x, pt_bl_y = :pt_bl_y,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
            """
        ),
        {
            "id": slide_id,
            **point_params,
        },
    )
    db.commit()
    return {"id": slide_id, "status": "REVIEWED"}


@router.get("/{slide_id}/result")
def get_slide_result(slide_id: int, db: Session = Depends(get_db)):
    row = _load_slide_or_404(db, slide_id)
    if not row.result_path:
        raise HTTPException(status_code=404, detail="Result is not generated yet")
    result_path = Path(row.result_path)
    if not result_path.exists():
        raise HTTPException(status_code=404, detail="Result image file not found")
    return FileResponse(path=str(result_path), media_type="image/jpeg")


@router.put("/{slide_id}")
def update_slide(slide_id: int, payload: SlideUpdateRequest, db: Session = Depends(get_db)):
    _load_slide_or_404(db, slide_id)
    normalized_tag = _normalize_tag(payload.tag)
    db.execute(
        text(
            """
            UPDATE slides
            SET tag = :tag,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
            """
        ),
        {"id": slide_id, "tag": normalized_tag},
    )
    db.commit()

    row = _load_slide_or_404(db, slide_id)
    return {
        "id": row.id,
        "status": row.status,
        "tag": row.tag,
        "updated_at": row.updated_at,
    }

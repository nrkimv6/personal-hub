"""Folder scan service for slide scanner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageOps
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.image_classifier.config import settings as ic_settings
from app.modules.slide_scanner.config import settings

from .metadata import extract_slide_metadata
from .rectifier_client import DetectMeta, rectifier_client


THUMBNAIL_SIZE = (200, 200)


def _normalize_path(path: Path | str) -> str:
    try:
        return str(Path(path).resolve(strict=False))
    except Exception:
        return str(path)


def _iter_images(folder_path: Path, recursive: bool = True):
    extensions = {ext.lower() for ext in ic_settings.IMAGE_EXTENSIONS}
    iterator = folder_path.rglob("*") if recursive else folder_path.glob("*")
    for candidate in iterator:
        if candidate.is_file() and candidate.suffix.lower() in extensions:
            yield candidate


def _thumbnail_to_jpeg_bytes(image: Image.Image) -> bytes:
    thumb = image.copy()
    if thumb.mode not in ("RGB", "L"):
        thumb = thumb.convert("RGB")
    thumb.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)

    from io import BytesIO

    buffer = BytesIO()
    thumb.save(buffer, format="JPEG", quality=settings.THUMBNAIL_QUALITY, optimize=True)
    return buffer.getvalue()


def _default_points(width: int, height: int) -> list[tuple[float, float]]:
    return [
        (0.0, 0.0),
        (float(width), 0.0),
        (float(width), float(height)),
        (0.0, float(height)),
    ]


def _points_to_params(points: list[tuple[float, float]]) -> dict[str, float]:
    return {
        "pt_tl_x": float(points[0][0]),
        "pt_tl_y": float(points[0][1]),
        "pt_tr_x": float(points[1][0]),
        "pt_tr_y": float(points[1][1]),
        "pt_br_x": float(points[2][0]),
        "pt_br_y": float(points[2][1]),
        "pt_bl_x": float(points[3][0]),
        "pt_bl_y": float(points[3][1]),
    }


def _detect_meta_to_params(meta: DetectMeta | None) -> dict[str, Any]:
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


def scan_folder(
    db: Session,
    folder_path: Path,
    recursive: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    root = folder_path.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Invalid folder path: {root}")

    existing_rows = db.execute(text("SELECT file_path FROM slides")).fetchall()
    existing_paths = {_normalize_path(row.file_path) for row in existing_rows}

    scanned = 0
    created = 0
    skipped = 0
    failed = 0
    errors: list[dict[str, str]] = []

    for image_path in _iter_images(root, recursive=recursive):
        if limit is not None and scanned >= limit:
            break

        scanned += 1
        normalized = _normalize_path(image_path)
        if normalized in existing_paths:
            skipped += 1
            continue

        try:
            with Image.open(image_path) as opened:
                image = ImageOps.exif_transpose(opened)
                width, height = image.size
                captured_at, source_app = extract_slide_metadata(image_path, image)
                thumbnail = _thumbnail_to_jpeg_bytes(image)

            try:
                detect_result = rectifier_client.detect_with_meta(image_path)
                points = detect_result["points"]
                detect_meta = detect_result["meta"]
                if len(points) != 4:
                    points = _default_points(width, height)
                    detect_meta = None
            except Exception:
                points = _default_points(width, height)
                detect_meta = None

            db.execute(
                text(
                    """
                    INSERT INTO slides (
                        file_name, file_path, status,
                        pt_tl_x, pt_tl_y, pt_tr_x, pt_tr_y, pt_br_x, pt_br_y, pt_bl_x, pt_bl_y,
                        detect_engine, detect_confidence, detect_fallback_reason,
                        captured_at, source_app, thumbnail, is_archived
                    ) VALUES (
                        :file_name, :file_path, 'PENDING',
                        :pt_tl_x, :pt_tl_y, :pt_tr_x, :pt_tr_y, :pt_br_x, :pt_br_y, :pt_bl_x, :pt_bl_y,
                        :detect_engine, :detect_confidence, :detect_fallback_reason,
                        :captured_at, :source_app, :thumbnail, 0
                    )
                    """
                ),
                {
                    "file_name": image_path.name,
                    "file_path": normalized,
                    "captured_at": captured_at,
                    "source_app": source_app,
                    "thumbnail": thumbnail,
                    **_points_to_params(points),
                    **_detect_meta_to_params(detect_meta),
                },
            )
            db.commit()
            created += 1
            existing_paths.add(normalized)
        except Exception as exc:
            db.rollback()
            failed += 1
            errors.append({"file_path": str(image_path), "error": str(exc)})

    return {
        "folder_path": str(root),
        "recursive": recursive,
        "scanned": scanned,
        "created": created,
        "skipped": skipped,
        "failed": failed,
        "errors": errors[:20],
    }

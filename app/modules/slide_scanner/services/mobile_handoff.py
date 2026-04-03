"""Handoff service from mobile ingest queue to slide scanner slides."""

from __future__ import annotations

import shutil
from io import BytesIO
from pathlib import Path

from PIL import Image
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.services.mobile_delete import cleanup_local_inbox_file


def _sanitize_segment(raw: str) -> str:
    invalid = '<>:"/\\|?*'
    cleaned = "".join("_" if char in invalid else char for char in raw.strip())
    cleaned = cleaned.rstrip(".")
    return cleaned or "unknown"


def _build_mobile_slide_path(device_id: str, original_filename: str) -> Path:
    target_dir = settings.ORIGINALS_DIR / "mobile" / _sanitize_segment(device_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    source_name = _sanitize_segment(original_filename)
    stem = Path(source_name).stem or "image"
    suffix = Path(source_name).suffix or ".jpg"
    candidate = target_dir / f"{stem}{suffix}"
    seq = 1
    while candidate.exists():
        candidate = target_dir / f"{stem}_{seq}{suffix}"
        seq += 1
    return candidate


def _build_thumbnail_bytes(image_path: Path) -> bytes:
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        rgb.thumbnail(settings.THUMBNAIL_SIZE)
        buffer = BytesIO()
        rgb.save(buffer, format="JPEG", quality=settings.THUMBNAIL_QUALITY)
        return buffer.getvalue()


def handoff_item_to_slides(db: Session, item_id: int) -> int:
    row = db.execute(
        text("SELECT * FROM mobile_ingest_items WHERE id = :id"),
        {"id": item_id},
    ).fetchone()
    if not row:
        raise ValueError("Mobile ingest item not found")

    if row.handoff_status == "DONE" and row.slide_id:
        return int(row.slide_id)

    if row.approval_status != "APPROVED":
        raise ValueError("Item is not approved")

    if row.remote_delete_status != "DONE":
        raise ValueError("Remote delete is not completed")

    source_path = Path(str(row.pc_inbox_path))
    if not source_path.exists():
        raise FileNotFoundError(f"Inbox image file not found: {source_path}")

    target_path = _build_mobile_slide_path(
        device_id=str(row.device_id),
        original_filename=str(row.original_filename),
    )
    shutil.copy2(source_path, target_path)
    thumbnail = _build_thumbnail_bytes(target_path)

    source_app = f"mobile:{row.device_id}"
    db.execute(
        text(
            """
            INSERT INTO slides (
                file_name,
                file_path,
                status,
                captured_at,
                source_app,
                source_device_id,
                thumbnail,
                is_archived
            ) VALUES (
                :file_name,
                :file_path,
                'PENDING',
                :captured_at,
                :source_app,
                :source_device_id,
                :thumbnail,
                0
            )
            """
        ),
        {
            "file_name": str(row.original_filename),
            "file_path": str(target_path),
            "captured_at": str(row.captured_at_utc),
            "source_app": source_app,
            "source_device_id": str(row.device_id),
            "thumbnail": thumbnail,
        },
    )
    slide_id = db.execute(text("SELECT last_insert_rowid()")).scalar_one()

    db.execute(
        text(
            """
            UPDATE mobile_ingest_items
            SET slide_id = :slide_id,
                handoff_status = 'DONE',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :item_id
            """
        ),
        {
            "item_id": item_id,
            "slide_id": int(slide_id),
        },
    )
    db.commit()

    cleanup_local_inbox_file(db, item_id)
    return int(slide_id)


__all__ = [
    "handoff_item_to_slides",
]

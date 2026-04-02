"""Archive service for processed slide originals."""

from __future__ import annotations

import hashlib
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.slide_scanner.config import settings


def _build_in_clause(ids: list[int]) -> tuple[str, dict[str, int]]:
    placeholders = []
    params: dict[str, int] = {}
    for index, value in enumerate(ids):
        key = f"id_{index}"
        placeholders.append(f":{key}")
        params[key] = value
    return ", ".join(placeholders), params


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def archive_done_slides(db: Session, slide_ids: list[int]) -> dict[str, Any]:
    unique_ids = list(dict.fromkeys(slide_ids))
    if not unique_ids:
        return {
            "archive_path": None,
            "requested": 0,
            "archived": 0,
            "skipped": [],
        }

    in_clause, in_params = _build_in_clause(unique_ids)
    rows = db.execute(
        text(
            f"""
            SELECT id, file_path, status, is_archived
            FROM slides
            WHERE id IN ({in_clause})
            """
        ),
        in_params,
    ).fetchall()
    row_map = {int(row.id): row for row in rows}

    eligible: list[Any] = []
    skipped: list[dict[str, Any]] = []

    for slide_id in unique_ids:
        row = row_map.get(slide_id)
        if not row:
            skipped.append({"id": slide_id, "reason": "not_found"})
            continue
        if row.status != "DONE":
            skipped.append({"id": slide_id, "reason": "not_done"})
            continue
        if int(row.is_archived or 0) == 1:
            skipped.append({"id": slide_id, "reason": "already_archived"})
            continue

        original_path = Path(row.file_path)
        if not original_path.exists():
            skipped.append({"id": slide_id, "reason": "original_missing"})
            continue
        eligible.append(row)

    if not eligible:
        return {
            "archive_path": None,
            "requested": len(unique_ids),
            "archived": 0,
            "skipped": skipped,
        }

    archive_name = f"slides_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    archive_path = settings.ARCHIVE_DIR / archive_name

    manifest: list[dict[str, str | int]] = []

    try:
        with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for row in eligible:
                file_path = Path(row.file_path)
                arcname = f"{row.id}_{file_path.name}"
                archive.write(file_path, arcname=arcname)
                manifest.append(
                    {
                        "id": int(row.id),
                        "file_path": str(file_path),
                        "arcname": arcname,
                        "sha256": _sha256_file(file_path),
                    }
                )

        with zipfile.ZipFile(archive_path, mode="r") as archive:
            for entry in manifest:
                zipped = archive.read(str(entry["arcname"]))
                if _sha256_bytes(zipped) != entry["sha256"]:
                    raise RuntimeError(f"Hash mismatch for {entry['arcname']}")

        for entry in manifest:
            file_path = Path(str(entry["file_path"]))
            if file_path.exists():
                file_path.unlink()

            db.execute(
                text(
                    """
                    UPDATE slides
                    SET is_archived = 1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                    """
                ),
                {"id": int(entry["id"])},
            )

        db.commit()
        return {
            "archive_path": str(archive_path),
            "requested": len(unique_ids),
            "archived": len(manifest),
            "skipped": skipped,
        }
    except Exception:
        db.rollback()
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)
        raise

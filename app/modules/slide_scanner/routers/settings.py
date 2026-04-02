"""Settings endpoints for slide scanner."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.database import get_db

router = APIRouter(prefix="/settings", tags=["slide-scanner"])


class SettingsUpdateRequest(BaseModel):
    scan_path: str | None = None
    output_path: str | None = None


def _load_settings(db: Session) -> dict[str, str]:
    rows = db.execute(text("SELECT key, value FROM scanner_settings")).fetchall()
    return {str(row.key): str(row.value) for row in rows}


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    values = _load_settings(db)
    return {
        "scan_path": values.get("scan_path"),
        "output_path": values.get("output_path", str(settings.OUTPUT_DIR)),
        "archive_path": values.get("archive_path", str(settings.ARCHIVE_DIR)),
    }


@router.put("")
def update_settings(request: SettingsUpdateRequest, db: Session = Depends(get_db)):
    updates: dict[str, str] = {}
    if request.scan_path is not None:
        updates["scan_path"] = request.scan_path.strip()
    if request.output_path is not None:
        output = Path(request.output_path.strip())
        output.mkdir(parents=True, exist_ok=True)
        updates["output_path"] = str(output)

    for key, value in updates.items():
        db.execute(
            text(
                """
                INSERT INTO scanner_settings (key, value)
                VALUES (:key, :value)
                ON CONFLICT(key)
                DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """
            ),
            {"key": key, "value": value},
        )

    if updates:
        db.commit()

    return get_settings(db)

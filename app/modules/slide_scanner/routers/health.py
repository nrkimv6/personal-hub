"""Health endpoints for slide scanner module."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.database import get_db

router = APIRouter(prefix="/health", tags=["slide-scanner"])


@router.get("")
def get_health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
        db_error = None
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        db_error = str(exc)

    return {
        "status": "ok" if db_ok else "degraded",
        "module": "slide_scanner",
        "database": {
            "ok": db_ok,
            "error": db_error,
        },
        "rectifier": {
            "root": str(settings.RECTIFIER_ROOT),
            "root_exists": settings.RECTIFIER_ROOT.exists(),
            "python": str(settings.RECTIFIER_PYTHON),
            "python_exists": settings.RECTIFIER_PYTHON.exists(),
        },
        "storage": {
            "data_dir": str(settings.DATA_DIR),
            "originals_dir": str(settings.ORIGINALS_DIR),
            "output_dir": str(settings.OUTPUT_DIR),
        },
    }

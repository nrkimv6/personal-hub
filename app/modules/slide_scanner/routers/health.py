"""Health endpoints for slide scanner module."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.database import get_db
from app.modules.slide_scanner.services.mobile_sync import list_connected_devices

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

    adb_path_config = str(settings.ADB_PATH)
    if settings.ADB_PATH.is_absolute():
        adb_resolved = settings.ADB_PATH
        adb_exists = adb_resolved.exists()
    else:
        adb_found = shutil.which(adb_path_config)
        adb_resolved = Path(adb_found) if adb_found else Path(adb_path_config)
        adb_exists = bool(adb_found)

    if adb_exists:
        try:
            devices = list_connected_devices(settings.ADB_PATH)
            adb_ok = True
            adb_error = None
        except Exception as exc:  # noqa: BLE001
            devices = []
            adb_ok = False
            adb_error = str(exc)
    else:
        devices = []
        adb_ok = False
        adb_error = "adb executable not found"

    try:
        inbox_exists = settings.MOBILE_INBOX_DIR.exists()
        inbox_file_count = (
            sum(1 for path in settings.MOBILE_INBOX_DIR.rglob("*") if path.is_file())
            if inbox_exists
            else 0
        )
        inbox_error = None
    except Exception as exc:  # noqa: BLE001
        inbox_exists = False
        inbox_file_count = 0
        inbox_error = str(exc)

    overall_ok = db_ok and adb_ok and inbox_exists and inbox_error is None

    return {
        "status": "ok" if overall_ok else "degraded",
        "module": "slide_scanner",
        "database": {
            "ok": db_ok,
            "error": db_error,
        },
        "adb": {
            "ok": adb_ok,
            "error": adb_error,
            "configured_path": adb_path_config,
            "resolved_path": str(adb_resolved),
            "executable_exists": adb_exists,
            "device_count": len(devices),
            "online_device_count": len([item for item in devices if item.get("is_online")]),
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
            "mobile_inbox_dir": str(settings.MOBILE_INBOX_DIR),
            "mobile_approved_dir": str(settings.MOBILE_APPROVED_DIR),
            "mobile_rejected_dir": str(settings.MOBILE_REJECTED_DIR),
            "mobile_inbox_exists": inbox_exists,
            "mobile_inbox_file_count": inbox_file_count,
            "mobile_inbox_error": inbox_error,
        },
    }

"""Mobile sync API endpoints for slide scanner pre-gate pipeline."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.modules.slide_scanner.config import parse_mobile_device_aliases, settings
from app.modules.slide_scanner.database import get_db
from app.modules.slide_scanner.services.mobile_sync import (
    get_sync_status,
    list_connected_devices,
    run_sync_background,
    run_sync_once,
)

router = APIRouter(prefix="/mobile-sync", tags=["slide-scanner"])


class MobileSyncRunRequest(BaseModel):
    background: bool = True


@router.get("/devices")
def get_mobile_sync_devices() -> dict[str, Any]:
    aliases = parse_mobile_device_aliases(settings.MOBILE_DEVICE_ALIAS_JSON)
    try:
        devices = list_connected_devices(settings.ADB_PATH)
        degraded = False
        error_message = None
    except Exception as exc:  # noqa: BLE001
        devices = []
        degraded = True
        error_message = str(exc)
    payload = []
    for device in devices:
        serial = str(device.get("serial") or "")
        payload.append(
            {
                **device,
                "alias": aliases.get(serial),
            }
        )
    return {
        "status": "degraded" if degraded else "ok",
        "error": error_message,
        "devices": payload,
        "total": len(payload),
        "online": len([item for item in payload if item.get("is_online")]),
    }


@router.post("/run")
def run_mobile_sync(
    request: MobileSyncRunRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if request.background:
        return run_sync_background()
    return run_sync_once(db)


@router.get("/status")
def get_mobile_sync_status() -> dict[str, Any]:
    return get_sync_status()

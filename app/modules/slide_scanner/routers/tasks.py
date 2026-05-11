"""Task status endpoints for slide scanner."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.modules.slide_scanner.services.task_store import get_task

router = APIRouter(prefix="/tasks", tags=["slide-scanner"])


class SlideScannerTaskStatusResponse(BaseModel):
    task_id: str
    kind: str
    status: str
    result: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None


@router.get("/{task_id}", response_model=SlideScannerTaskStatusResponse)
def get_slide_scanner_task(task_id: str):
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Slide scanner task not found")
    return task

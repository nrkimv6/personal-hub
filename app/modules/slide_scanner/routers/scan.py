"""Folder scan endpoint for slide scanner."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.modules.slide_scanner.database import get_db
from app.modules.slide_scanner.services.scanner import scan_folder

router = APIRouter(prefix="/scan", tags=["slide-scanner"])


class ScanRequest(BaseModel):
    folder_path: str = Field(..., min_length=1)
    recursive: bool = True
    limit: int | None = Field(default=None, ge=1, le=50000)


@router.post("")
def scan(request: ScanRequest, db: Session = Depends(get_db)):
    try:
        return scan_folder(
            db=db,
            folder_path=Path(request.folder_path),
            recursive=request.recursive,
            limit=request.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

"""Archive endpoints for slide scanner."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.modules.slide_scanner.database import get_db
from app.modules.slide_scanner.services.archiver import archive_done_slides

router = APIRouter(prefix="/archive", tags=["slide-scanner"])


class ArchiveRequest(BaseModel):
    ids: list[int] = Field(..., min_length=1)


@router.post("")
def archive_slides(request: ArchiveRequest, db: Session = Depends(get_db)):
    try:
        return archive_done_slides(db, request.ids)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Archive failed: {exc}") from exc

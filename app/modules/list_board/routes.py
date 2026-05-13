"""List Board API 라우트."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.modules.list_board.schemas import (
    ListBoardImportRequest, ListBoardItemImportResult, ListBoardListResponse
)
from app.modules.list_board import services

router = APIRouter(prefix="/api/v1/list-board", tags=["List Board"])


@router.post("/import", response_model=ListBoardItemImportResult)
def import_items(req: ListBoardImportRequest, db: Session = Depends(get_db)):
    return services.import_items(db, req)


@router.get("/items", response_model=ListBoardListResponse)
def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    source: Optional[str] = Query(None),
    badge_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    return services.list_items(db, page=page, page_size=page_size, source=source, badge_type=badge_type)

"""List Board API 라우트."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.list_board.schemas import (
    ColumnCreate,
    ColumnResponse,
    ColumnUpdate,
    ItemPropertiesPatch,
    ListBoardImportRequest,
    ListBoardItemImportResult,
    ListBoardItemResponse,
    ListBoardListResponse,
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
    sort_by: Optional[str] = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    return services.list_items(
        db, page=page, page_size=page_size,
        source=source, badge_type=badge_type,
        sort_by=sort_by, sort_order=sort_order,
    )


@router.patch("/items/{item_id}/properties", response_model=ListBoardItemResponse)
def patch_item_properties(item_id: int, req: ItemPropertiesPatch, db: Session = Depends(get_db)):
    return services.patch_item_properties(db, item_id, req)


# ── Column endpoints ─────────────────────────────────────────────────────────

@router.get("/columns", response_model=List[ColumnResponse])
def list_columns(db: Session = Depends(get_db)):
    return services.list_columns(db)


@router.post("/columns", response_model=ColumnResponse, status_code=201)
def create_column(req: ColumnCreate, db: Session = Depends(get_db)):
    return services.create_column(db, req)


@router.patch("/columns/{column_id}", response_model=ColumnResponse)
def update_column(column_id: int, req: ColumnUpdate, db: Session = Depends(get_db)):
    return services.update_column(db, column_id, req)


@router.delete("/columns/{column_id}", status_code=204)
def delete_column(column_id: int, db: Session = Depends(get_db)):
    services.delete_column(db, column_id)


# ── Sources summary ──────────────────────────────────────────────────────────

@router.get("/sources", response_model=List[Dict[str, Any]])
def list_sources(db: Session = Depends(get_db)):
    return services.list_sources(db)

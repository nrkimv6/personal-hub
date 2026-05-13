"""List Board 서비스 — import, upsert, list, column CRUD, properties patch, sort."""

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.modules.list_board.models import ListBoardColumn, ListBoardItem
from app.modules.list_board.parser import parse_markdown_table
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

# system column keys — sort allowlist
_SYSTEM_SORT_KEYS = {"title", "url", "duration_minutes", "source", "badge_type", "created_at", "updated_at"}


def import_items(db: Session, req: ListBoardImportRequest) -> ListBoardItemImportResult:
    """Markdown 표를 파싱하여 items를 upsert한다."""
    result = parse_markdown_table(req.markdown_text)
    created = 0
    updated = 0
    skipped = 0
    errors = list(result.errors)

    for item in result.items:
        existing = db.query(ListBoardItem).filter_by(url=item.url).first()
        if existing is None:
            db.add(ListBoardItem(
                title=item.title,
                url=item.url,
                duration_minutes=item.duration_minutes,
                source=req.source,
                badge_type=req.badge_type,
                properties={},
            ))
            created += 1
        else:
            existing.title = item.title
            if item.duration_minutes is not None:
                existing.duration_minutes = item.duration_minutes
            existing.source = req.source
            if req.badge_type is not None:
                existing.badge_type = req.badge_type
            updated += 1

    db.commit()
    return ListBoardItemImportResult(created=created, updated=updated, skipped=skipped, errors=errors)


def list_items(
    db: Session,
    page: int = 1,
    page_size: int = 50,
    source: Optional[str] = None,
    badge_type: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: str = "asc",
) -> ListBoardListResponse:
    """아이템 목록 조회 — page/source/badge_type 필터 + sort."""
    q = db.query(ListBoardItem)
    if source:
        q = q.filter(ListBoardItem.source == source)
    if badge_type:
        q = q.filter(ListBoardItem.badge_type == badge_type)

    if sort_by:
        direction = "asc" if sort_order.lower() != "desc" else "desc"
        if sort_by in _SYSTEM_SORT_KEYS:
            col_attr = getattr(ListBoardItem, sort_by, None)
            if col_attr is not None:
                q = q.order_by(col_attr.desc() if direction == "desc" else col_attr.asc())
            else:
                q = q.order_by(ListBoardItem.created_at.desc())
        else:
            # custom column: sort by properties JSON — fallback to created_at for unsupported backends
            q = q.order_by(ListBoardItem.created_at.desc())
    else:
        q = q.order_by(ListBoardItem.created_at.desc())

    total = q.count()
    offset = (page - 1) * page_size
    items = q.offset(offset).limit(page_size).all()

    return ListBoardListResponse(
        items=[ListBoardItemResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ── Column CRUD ─────────────────────────────────────────────────────────────

def list_columns(db: Session) -> List[ColumnResponse]:
    cols = db.query(ListBoardColumn).order_by(ListBoardColumn.sort_order, ListBoardColumn.id).all()
    return [_col_to_response(c) for c in cols]


def create_column(db: Session, req: ColumnCreate) -> ColumnResponse:
    dup = db.query(ListBoardColumn).filter_by(key=req.key).first()
    if dup:
        raise HTTPException(status_code=409, detail=f"column key '{req.key}' already exists")
    col = ListBoardColumn(
        key=req.key,
        display_name=req.display_name,
        column_type=req.column_type,
        options=req.options,
        sort_order=req.sort_order,
        is_visible=1,
    )
    db.add(col)
    db.commit()
    db.refresh(col)
    return _col_to_response(col)


def update_column(db: Session, column_id: int, req: ColumnUpdate) -> ColumnResponse:
    col = _get_column_or_404(db, column_id)
    if req.display_name is not None:
        col.display_name = req.display_name
    if req.options is not None:
        col.options = req.options
    if req.sort_order is not None:
        col.sort_order = req.sort_order
    if req.is_visible is not None:
        col.is_visible = 1 if req.is_visible else 0
    db.commit()
    db.refresh(col)
    return _col_to_response(col)


def delete_column(db: Session, column_id: int) -> None:
    col = _get_column_or_404(db, column_id)
    db.delete(col)
    db.commit()


# ── Properties patch ─────────────────────────────────────────────────────────

def patch_item_properties(db: Session, item_id: int, req: ItemPropertiesPatch) -> ListBoardItemResponse:
    """요청한 key만 shallow merge — 나머지 properties 보존."""
    item = db.query(ListBoardItem).filter_by(id=item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")

    cols = {c.key: c for c in db.query(ListBoardColumn).all()}
    validated = _validate_properties(req.properties, cols)

    current = dict(item.properties or {})
    current.update(validated)
    item.properties = current
    db.commit()
    db.refresh(item)
    return ListBoardItemResponse.model_validate(item)


# ── Sources summary ──────────────────────────────────────────────────────────

def list_sources(db: Session) -> List[Dict[str, Any]]:
    """source별 count와 최신 updated_at 요약."""
    from sqlalchemy import func
    rows = (
        db.query(
            ListBoardItem.source,
            func.count(ListBoardItem.id).label("count"),
            func.max(ListBoardItem.updated_at).label("last_import_at"),
        )
        .group_by(ListBoardItem.source)
        .order_by(func.max(ListBoardItem.updated_at).desc())
        .all()
    )
    return [{"source": r.source, "count": r.count, "last_import_at": r.last_import_at} for r in rows]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_column_or_404(db: Session, column_id: int) -> ListBoardColumn:
    col = db.query(ListBoardColumn).filter_by(id=column_id).first()
    if col is None:
        raise HTTPException(status_code=404, detail="column not found")
    return col


def _col_to_response(c: ListBoardColumn) -> ColumnResponse:
    return ColumnResponse(
        id=c.id,
        key=c.key,
        display_name=c.display_name,
        column_type=c.column_type,
        options=list(c.options) if c.options else [],
        sort_order=c.sort_order,
        is_visible=bool(c.is_visible),
        created_at=c.created_at,
    )


def _validate_properties(props: Dict[str, Any], cols: Dict[str, ListBoardColumn]) -> Dict[str, Any]:
    """타입별 검증 — 실패 시 400."""
    validated: Dict[str, Any] = {}
    for key, value in props.items():
        col = cols.get(key)
        if col is None:
            raise HTTPException(status_code=400, detail=f"unknown column key: '{key}'")
        if col.column_type == "checkbox":
            if not isinstance(value, bool):
                raise HTTPException(status_code=400, detail=f"column '{key}' expects bool")
        elif col.column_type == "text":
            if value is not None and not isinstance(value, str):
                raise HTTPException(status_code=400, detail=f"column '{key}' expects string or null")
        elif col.column_type == "select":
            allowed = list(col.options or [])
            if value is not None and value not in allowed:
                raise HTTPException(status_code=400, detail=f"column '{key}' value must be one of {allowed}")
        elif col.column_type == "priority":
            if value is not None and value not in ("low", "medium", "high", "critical"):
                raise HTTPException(status_code=400, detail=f"column '{key}' priority must be low/medium/high/critical")
        validated[key] = value
    return validated

"""List Board 서비스 — import, upsert, list."""

from typing import Optional

from sqlalchemy.orm import Session

from app.modules.list_board.models import ListBoardItem
from app.modules.list_board.parser import parse_markdown_table
from app.modules.list_board.schemas import (
    ListBoardImportRequest,
    ListBoardItemImportResult,
    ListBoardItemResponse,
    ListBoardListResponse,
)


def import_items(db: Session, req: ListBoardImportRequest) -> ListBoardItemImportResult:
    """Markdown 표를 파싱하여 items를 upsert한다."""
    result = parse_markdown_table(req.markdown_text)
    created = 0
    updated = 0
    skipped = 0
    errors = list(result.errors)

    for item in result.items:
        # URL 기준 존재 여부 확인
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
            # system field만 갱신, properties는 보존
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
) -> ListBoardListResponse:
    """아이템 목록 조회 — page/source/badge_type 필터."""
    q = db.query(ListBoardItem)
    if source:
        q = q.filter(ListBoardItem.source == source)
    if badge_type:
        q = q.filter(ListBoardItem.badge_type == badge_type)

    total = q.count()
    offset = (page - 1) * page_size
    items = q.order_by(ListBoardItem.created_at.desc()).offset(offset).limit(page_size).all()

    return ListBoardListResponse(
        items=[ListBoardItemResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )

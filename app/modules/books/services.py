"""Books service layer."""

import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.modules.books.models import Book, Highlight
from app.modules.books.schemas import BookCreate, BookUpdate, HighlightCreate


def statuses_for_disposal(disposal: str) -> dict[str, str]:
    """Return status side effects for a disposal decision."""
    return {
        "sell_status": "ready" if disposal == "sell" else "none",
        "scan_status": "ready" if disposal == "scan" else "none",
        "discard_status": "ready" if disposal == "discard" else "none",
    }


def _encode_tags(tags: list[str]) -> str:
    return json.dumps(tags, ensure_ascii=False)


def _decode_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def _highlight_to_dict(highlight: Highlight) -> dict:
    return {
        "id": highlight.id,
        "book_id": highlight.book_id,
        "page": highlight.page,
        "quote": highlight.quote,
        "memo": highlight.memo,
        "tags": _decode_tags(highlight.tags),
        "importance": highlight.importance,
        "photo": highlight.photo,
        "created_at": highlight.created_at,
    }


def book_to_dict(book: Book) -> dict:
    return {
        "id": book.id,
        "isbn": book.isbn,
        "title": book.title,
        "author": book.author,
        "publisher": book.publisher,
        "published_year": book.published_year,
        "price": book.price,
        "category": book.category,
        "cover_url": book.cover_url,
        "condition": book.condition,
        "location": book.location,
        "purchased_where": book.purchased_where,
        "purchased_used": None if book.purchased_used is None else book.purchased_used == "true",
        "purchased_price": book.purchased_price,
        "reason": book.reason,
        "reread_intent": book.reread_intent,
        "notes": book.notes,
        "accessibility_library": book.accessibility_library,
        "accessibility_millie": book.accessibility_millie,
        "accessibility_ebook": book.accessibility_ebook,
        "accessibility_used_buyback": book.accessibility_used_buyback,
        "used_buyback_price": book.used_buyback_price,
        "last_checked_at": book.last_checked_at,
        "recommendation": book.recommendation,
        "disposal": book.disposal,
        "sell_status": book.sell_status,
        "scan_status": book.scan_status,
        "discard_status": book.discard_status,
        "scan_purpose": book.scan_purpose,
        "review_date": book.review_date,
        "highlights": [_highlight_to_dict(item) for item in book.highlights],
        "created_at": book.created_at,
        "updated_at": book.updated_at,
    }


def _apply_disposal_side_effects(book: Book, disposal: str) -> None:
    book.disposal = disposal
    for field, value in statuses_for_disposal(disposal).items():
        setattr(book, field, value)


def _create_highlight_model(data: HighlightCreate) -> Highlight:
    return Highlight(
        page=data.page,
        quote=data.quote,
        memo=data.memo,
        tags=_encode_tags(data.tags),
        importance=data.importance,
        photo=data.photo,
    )


def list_books(
    db: Session,
    offset: int = 0,
    limit: int = 24,
    disposal: str | None = None,
    search: str | None = None,
) -> dict:
    query = db.query(Book)
    if disposal and disposal != "all":
        query = query.filter(Book.disposal == disposal)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(Book.title.ilike(pattern), Book.author.ilike(pattern), Book.isbn.ilike(pattern))
        )
    total = query.count()
    items = query.order_by(Book.updated_at.desc(), Book.id.desc()).offset(offset).limit(limit).all()
    return {"items": [book_to_dict(item) for item in items], "total": total, "offset": offset, "limit": limit}


def get_book(db: Session, book_id: int) -> Book | None:
    return db.query(Book).filter(Book.id == book_id).first()


def create_book(db: Session, data: BookCreate) -> Book:
    existing = db.query(Book).filter(Book.isbn == data.isbn).first()
    if existing:
        raise HTTPException(status_code=409, detail="이미 등록된 ISBN입니다.")
    payload = data.model_dump(exclude={"highlights"})
    payload["purchased_used"] = None if data.purchased_used is None else str(data.purchased_used).lower()
    book = Book(**payload)
    _apply_disposal_side_effects(book, data.disposal)
    for highlight in data.highlights:
        book.highlights.append(_create_highlight_model(highlight))
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


def update_book(db: Session, book_id: int, data: BookUpdate) -> Book:
    book = get_book(db, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="책을 찾을 수 없습니다.")
    payload = data.model_dump(exclude_unset=True)
    disposal = payload.pop("disposal", None)
    if "purchased_used" in payload:
        value = payload["purchased_used"]
        payload["purchased_used"] = None if value is None else str(value).lower()
    for field, value in payload.items():
        setattr(book, field, value)
    if disposal is not None:
        _apply_disposal_side_effects(book, disposal)
    book.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(book)
    return book


def delete_book(db: Session, book_id: int) -> bool:
    book = get_book(db, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="책을 찾을 수 없습니다.")
    db.delete(book)
    db.commit()
    return True


def list_highlights(db: Session, book_id: int) -> list[dict]:
    book = get_book(db, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="책을 찾을 수 없습니다.")
    return [_highlight_to_dict(item) for item in book.highlights]


def create_highlight(db: Session, book_id: int, data: HighlightCreate) -> Highlight:
    book = get_book(db, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="책을 찾을 수 없습니다.")
    highlight = _create_highlight_model(data)
    book.highlights.append(highlight)
    book.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(highlight)
    return highlight


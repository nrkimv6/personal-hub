"""Books service layer."""

import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.modules.books.aladin_buyback import ALADIN_GRADES, AladinBuybackResult, fetch_aladin_buyback, normalize_isbn
from app.modules.books.models import Book, BookBuybackQuote, Highlight
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


def _quote_to_dict(quote: BookBuybackQuote) -> dict:
    return {
        "id": quote.id,
        "provider": quote.provider,
        "grade": quote.grade,
        "price": quote.price,
        "currency": quote.currency,
        "availability": quote.availability,
        "raw_status": quote.raw_status,
        "message": quote.message,
        "checked_at": quote.checked_at,
    }


def latest_buyback_quotes(book: Book) -> list[BookBuybackQuote]:
    by_grade = {quote.grade: quote for quote in book.buyback_quotes if quote.provider == "aladin" and quote.grade in ALADIN_GRADES}
    return [by_grade[grade] for grade in ALADIN_GRADES if grade in by_grade]


def grade_for_condition(condition: str) -> str | None:
    return {
        "mint": "최상",
        "good": "상",
        "fair": "중",
    }.get(condition)


def buyback_recommendation(book: Book) -> dict:
    grade = grade_for_condition(book.condition)
    if grade is None:
        return {
            "grade": None,
            "price": None,
            "action": "user_review",
            "message": "현재 책 상태는 알라딘 중고 매입 가능 여부를 사용자가 확인해야 합니다.",
        }
    quotes = {quote.grade: quote for quote in latest_buyback_quotes(book)}
    quote = quotes.get(grade)
    if not quote or quote.price is None:
        return {"grade": grade, "price": None, "action": "unknown", "message": "상태에 맞는 알라딘 매입가가 아직 없습니다."}
    return {"grade": grade, "price": quote.price, "action": "sell", "message": f"현재 상태 기준 {grade} 매입가"}


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
        "buyback_quotes": [_quote_to_dict(item) for item in latest_buyback_quotes(book)],
        "buyback_recommendation": buyback_recommendation(book),
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


def _upsert_aladin_quotes(db: Session, book: Book, result: AladinBuybackResult) -> None:
    now = result.checked_at
    existing = {
        quote.grade: quote
        for quote in db.query(BookBuybackQuote)
        .filter(BookBuybackQuote.book_id == book.id, BookBuybackQuote.provider == "aladin")
        .all()
    }
    for result_quote in result.quotes:
        current = existing.get(result_quote.grade)
        if current and current.checked_at and current.checked_at > now:
            continue
        if current is None:
            current = BookBuybackQuote(book_id=book.id, provider="aladin", grade=result_quote.grade)
            db.add(current)
        current.price = result_quote.price
        current.currency = "KRW"
        current.availability = "yes"
        current.raw_status = result.raw_status
        current.message = result.message
        current.checked_at = now
        current.updated_at = datetime.utcnow()


def _apply_buyback_summary(book: Book, result: AladinBuybackResult) -> None:
    today = result.checked_at.date().isoformat()
    book.last_checked_at = today
    if result.availability == "yes":
        book.accessibility_used_buyback = "yes"
        grade = grade_for_condition(book.condition)
        prices = {quote.grade: quote.price for quote in result.quotes}
        book.used_buyback_price = prices.get(grade) if grade else None
        return
    if result.availability == "no" and book.used_buyback_price is None:
        book.accessibility_used_buyback = "no"
    elif result.availability == "error":
        book.accessibility_used_buyback = "check"


def refresh_aladin_buyback(db: Session, book_id: int, fetcher=None) -> dict:
    book = get_book(db, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="책을 찾을 수 없습니다.")
    isbn = normalize_isbn(book.isbn)
    if not isbn:
        raise HTTPException(status_code=400, detail="ISBN이 없어 알라딘 매입가를 조회할 수 없습니다.")

    fetch = fetcher or fetch_aladin_buyback
    result = fetch(isbn)
    if result.availability == "yes":
        _upsert_aladin_quotes(db, book, result)
    _apply_buyback_summary(book, result)
    book.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(book)
    quotes = [_quote_to_dict(item) for item in latest_buyback_quotes(book)]
    return {
        "book": book_to_dict(book),
        "quotes": quotes,
        "availability": result.availability,
        "message": result.message,
    }


"""Books service and schema tests."""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.modules.books.aladin_buyback import AladinBuybackQuote, AladinBuybackResult
from app.modules.books.models import Book, BookBuybackQuote, Highlight
from app.modules.books.schemas import BookCreate, BookUpdate, HighlightCreate
from app.modules.books.services import create_book, refresh_aladin_buyback, statuses_for_disposal, update_book


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'books_service.db'}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    tables = [Book.__table__, Highlight.__table__, BookBuybackQuote.__table__]
    Base.metadata.create_all(bind=engine, tables=tables)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine, tables=tables)
        engine.dispose()


def book_payload(**overrides):
    payload = {
        "isbn": "9780000000001",
        "title": "테스트 책",
        "author": "테스터",
        "publisher": "테스트 출판",
        "condition": "good",
        "accessibility_library": "yes",
        "accessibility_millie": "check",
        "accessibility_ebook": "yes",
        "accessibility_used_buyback": "no",
    }
    payload.update(overrides)
    return payload


def test_set_disposal_R_sets_ready_status(db):
    book = create_book(db, BookCreate(**book_payload()))
    updated = update_book(db, book.id, BookUpdate(disposal="sell"))

    assert updated.sell_status == "ready"
    assert updated.scan_status == "none"
    assert updated.discard_status == "none"


def test_set_disposal_R_scan_purpose_guillotine():
    assert statuses_for_disposal("scan") == {
        "sell_status": "none",
        "scan_status": "ready",
        "discard_status": "none",
    }


def test_set_disposal_B_empty_highlights(db):
    book = create_book(db, BookCreate(**book_payload(isbn="9780000000002", highlights=[])))
    updated = update_book(db, book.id, BookUpdate(disposal="discard"))

    assert updated.highlights == []
    assert updated.discard_status == "ready"


def test_set_disposal_E_invalid_disposal_value():
    with pytest.raises(ValidationError):
        BookUpdate(disposal="donate")


def test_book_schema_Co_required_fields():
    with pytest.raises(ValidationError):
        BookCreate(isbn="9780000000003", author="테스터")


def test_book_schema_R_accessibility_axes():
    with pytest.raises(ValidationError):
        BookCreate(**book_payload(accessibility_library="maybe"))


def test_highlight_schema_E_importance_existence():
    item = HighlightCreate(page=10, quote="좋은 문장")

    assert item.importance == 3


def test_refresh_aladin_buyback_R_upserts_condition_quotes(db):
    book = create_book(db, BookCreate(**book_payload(condition="good")))

    result = refresh_aladin_buyback(
        db,
        book.id,
        fetcher=lambda isbn: AladinBuybackResult(
            isbn=isbn,
            availability="yes",
            quotes=[
                AladinBuybackQuote("최상", 3000),
                AladinBuybackQuote("상", 2700),
                AladinBuybackQuote("중", 2400),
            ],
        ),
    )

    assert result["availability"] == "yes"
    assert {quote["grade"]: quote["price"] for quote in result["quotes"]} == {"최상": 3000, "상": 2700, "중": 2400}
    assert result["book"]["used_buyback_price"] == 2700
    assert result["book"]["buyback_recommendation"]["grade"] == "상"


def test_refresh_aladin_buyback_B_low_condition_needs_user_review(db):
    book = create_book(db, BookCreate(**book_payload(isbn="9780000000004", condition="marked")))

    result = refresh_aladin_buyback(
        db,
        book.id,
        fetcher=lambda isbn: AladinBuybackResult(
            isbn=isbn,
            availability="yes",
            quotes=[
                AladinBuybackQuote("최상", 3000),
                AladinBuybackQuote("상", 2700),
                AladinBuybackQuote("중", 2400),
            ],
        ),
    )

    assert result["book"]["used_buyback_price"] is None
    assert result["book"]["buyback_recommendation"]["action"] == "user_review"


def test_refresh_aladin_buyback_E_error_preserves_existing_success_quote(db):
    book = create_book(db, BookCreate(**book_payload(isbn="9780000000005", condition="fair")))
    refresh_aladin_buyback(
        db,
        book.id,
        fetcher=lambda isbn: AladinBuybackResult(
            isbn=isbn,
            availability="yes",
            checked_at=datetime.utcnow() - timedelta(minutes=1),
            quotes=[
                AladinBuybackQuote("최상", 3000),
                AladinBuybackQuote("상", 2700),
                AladinBuybackQuote("중", 2400),
            ],
        ),
    )

    result = refresh_aladin_buyback(
        db,
        book.id,
        fetcher=lambda isbn: AladinBuybackResult(isbn=isbn, availability="error", raw_status="timeout", message="timeout"),
    )

    assert result["availability"] == "error"
    assert {quote["grade"]: quote["price"] for quote in result["quotes"]}["중"] == 2400

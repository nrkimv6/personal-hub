"""Books CRUD API tests."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.modules.books.aladin_buyback import AladinBuybackQuote, AladinBuybackResult
from app.modules.books.models import Book, BookBuybackQuote, Highlight


@pytest.fixture()
def db_bundle(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'books_api.db'}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    tables = [Book.__table__, Highlight.__table__, BookBuybackQuote.__table__]
    Base.metadata.create_all(bind=engine, tables=tables)
    session = SessionLocal()
    try:
        yield {"session": session, "SessionLocal": SessionLocal, "engine": engine}
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine, tables=tables)
        engine.dispose()


@pytest.fixture()
def client(db_bundle):
    SessionLocal = db_bundle["SessionLocal"]

    def override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def payload(isbn="9780000000100", **overrides):
    data = {
        "isbn": isbn,
        "title": "API 테스트 책",
        "author": "테스터",
        "publisher": "테스트 출판",
        "condition": "good",
        "location": "서재",
        "accessibility_library": "yes",
        "accessibility_millie": "check",
        "accessibility_ebook": "yes",
        "accessibility_used_buyback": "no",
    }
    data.update(overrides)
    return data


def create_book(client: TestClient, isbn="9780000000100", **overrides) -> int:
    response = client.post("/api/v1/books", json=payload(isbn=isbn, **overrides))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_create_book_R_returns_201(client):
    response = client.post("/api/v1/books", json=payload())

    assert response.status_code == 201, response.text
    assert response.json()["id"] > 0


def test_list_books_R_pagination(client):
    create_book(client, isbn="9780000000101")
    create_book(client, isbn="9780000000102")

    response = client.get("/api/v1/books?offset=0&limit=1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 1
    assert body["total"] == 2


def test_list_books_B_empty(client):
    response = client.get("/api/v1/books?offset=0&limit=24")

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    assert response.json()["total"] == 0


def test_get_book_E_not_found(client):
    response = client.get("/api/v1/books/999999")

    assert response.status_code == 404


def test_patch_book_R_updates_disposal(client):
    book_id = create_book(client, isbn="9780000000103")

    response = client.patch(f"/api/v1/books/{book_id}", json={"disposal": "sell"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["disposal"] == "sell"
    assert body["sell_status"] == "ready"
    assert body["scan_status"] == "none"


def test_delete_book_R_then_404(client):
    book_id = create_book(client, isbn="9780000000104")

    delete_response = client.delete(f"/api/v1/books/{book_id}")
    get_response = client.get(f"/api/v1/books/{book_id}")

    assert delete_response.status_code == 200, delete_response.text
    assert get_response.status_code == 404


def test_book_highlights_R_list(client):
    book_id = create_book(
        client,
        isbn="9780000000105",
        highlights=[{"page": 12, "quote": "문장", "tags": ["태그"], "importance": 4}],
    )

    response = client.get(f"/api/v1/books/{book_id}/highlights")

    assert response.status_code == 200, response.text
    assert response.json()[0]["quote"] == "문장"


def test_set_disposal_side_effect_persists_to_db(client):
    book_id = create_book(client, isbn="9780000000106")
    client.patch(f"/api/v1/books/{book_id}", json={"disposal": "scan"})

    response = client.get(f"/api/v1/books/{book_id}")

    assert response.status_code == 200, response.text
    assert response.json()["scan_status"] == "ready"


def test_create_book_with_highlights_cascade(client):
    book_id = create_book(
        client,
        isbn="9780000000107",
        highlights=[{"page": 1, "quote": "첫 문장"}, {"page": 2, "quote": "둘째 문장"}],
    )

    response = client.get(f"/api/v1/books/{book_id}/highlights")

    assert response.status_code == 200, response.text
    assert len(response.json()) == 2


def test_list_books_filter_by_disposal_integration(client):
    create_book(client, isbn="9780000000108", disposal="sell")
    create_book(client, isbn="9780000000109", disposal="keep")

    response = client.get("/api/v1/books?disposal=sell")

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["disposal"] == "sell"


def test_refresh_aladin_buyback_R_returns_quotes(client, monkeypatch):
    from app.modules.books import services as svc

    book_id = create_book(client, isbn="9788937460449", condition="good")
    monkeypatch.setattr(
        svc,
        "fetch_aladin_buyback",
        lambda isbn: AladinBuybackResult(
            isbn=isbn,
            availability="yes",
            quotes=[
                AladinBuybackQuote("최상", 3000),
                AladinBuybackQuote("상", 2700),
                AladinBuybackQuote("중", 2400),
            ],
        ),
    )

    response = client.post(f"/api/v1/books/{book_id}/buyback/aladin/refresh")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["availability"] == "yes"
    assert {quote["grade"]: quote["price"] for quote in body["quotes"]} == {"최상": 3000, "상": 2700, "중": 2400}
    assert body["book"]["used_buyback_price"] == 2700


def test_refresh_aladin_buyback_E_error_keeps_book_row(client, monkeypatch):
    from app.modules.books import services as svc

    book_id = create_book(client, isbn="9788937460448", used_buyback_price=1200, accessibility_used_buyback="yes")
    monkeypatch.setattr(
        svc,
        "fetch_aladin_buyback",
        lambda isbn: AladinBuybackResult(isbn=isbn, availability="error", raw_status="timeout", message="timeout"),
    )

    response = client.post(f"/api/v1/books/{book_id}/buyback/aladin/refresh")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["availability"] == "error"
    assert body["book"]["used_buyback_price"] == 1200

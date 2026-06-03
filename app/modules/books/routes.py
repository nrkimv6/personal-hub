"""Books API routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.books import services as svc
from app.modules.books.schemas import (
    BookCreate,
    BookListResponse,
    BookResponse,
    BookUpdate,
    BuybackRefreshResponse,
    HighlightCreate,
    HighlightResponse,
)

router = APIRouter(prefix="/api/v1/books", tags=["Books"])


@router.get("", response_model=BookListResponse)
def get_books(
    offset: int = Query(0, ge=0),
    limit: int = Query(24, ge=1, le=100),
    disposal: str | None = Query(None),
    search: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return svc.list_books(db, offset=offset, limit=limit, disposal=disposal, search=search)


@router.post("", response_model=BookResponse, status_code=201)
def create_book(data: BookCreate, db: Session = Depends(get_db)):
    return svc.book_to_dict(svc.create_book(db, data))


@router.get("/{book_id}", response_model=BookResponse)
def get_book(book_id: int, db: Session = Depends(get_db)):
    book = svc.get_book(db, book_id)
    if not book:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="책을 찾을 수 없습니다.")
    return svc.book_to_dict(book)


@router.patch("/{book_id}", response_model=BookResponse)
def patch_book(book_id: int, data: BookUpdate, db: Session = Depends(get_db)):
    return svc.book_to_dict(svc.update_book(db, book_id, data))


@router.delete("/{book_id}")
def delete_book(book_id: int, db: Session = Depends(get_db)):
    svc.delete_book(db, book_id)
    return {"ok": True}


@router.get("/{book_id}/highlights", response_model=list[HighlightResponse])
def get_highlights(book_id: int, db: Session = Depends(get_db)):
    return svc.list_highlights(db, book_id)


@router.post("/{book_id}/highlights", response_model=HighlightResponse, status_code=201)
def create_highlight(book_id: int, data: HighlightCreate, db: Session = Depends(get_db)):
    return svc._highlight_to_dict(svc.create_highlight(db, book_id, data))


@router.post("/{book_id}/buyback/aladin/refresh", response_model=BuybackRefreshResponse)
def refresh_aladin_buyback(book_id: int, db: Session = Depends(get_db)):
    return svc.refresh_aladin_buyback(db, book_id)


"""Books module SQLAlchemy models."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Book(Base):
    """Personal library book."""

    __tablename__ = "books"

    id = Column(Integer, primary_key=True, autoincrement=True)
    isbn = Column(String(32), nullable=False, unique=True, index=True)
    title = Column(String(240), nullable=False)
    author = Column(String(160), nullable=False)
    publisher = Column(String(160), nullable=False, default="")
    published_year = Column(Integer, nullable=True)
    price = Column(Integer, nullable=True)
    category = Column(String(80), nullable=False, default="")
    cover_url = Column(Text, nullable=True)

    condition = Column(String(20), nullable=False, default="good")
    location = Column(String(240), nullable=False, default="")
    purchased_where = Column(String(160), nullable=True)
    purchased_used = Column(String(8), nullable=True)
    purchased_price = Column(Integer, nullable=True)
    reason = Column(Text, nullable=True)
    reread_intent = Column(Integer, nullable=False, default=3)
    notes = Column(Text, nullable=True)

    accessibility_library = Column(String(10), nullable=False, default="check")
    accessibility_millie = Column(String(10), nullable=False, default="check")
    accessibility_ebook = Column(String(10), nullable=False, default="check")
    accessibility_used_buyback = Column(String(10), nullable=False, default="check")
    used_buyback_price = Column(Integer, nullable=True)
    last_checked_at = Column(String(10), nullable=True)

    recommendation = Column(String(20), nullable=False, default="undecided")
    disposal = Column(String(20), nullable=False, default="undecided")
    sell_status = Column(String(20), nullable=False, default="none")
    scan_status = Column(String(20), nullable=False, default="none")
    discard_status = Column(String(20), nullable=False, default="none")
    scan_purpose = Column(String(30), nullable=True)
    review_date = Column(String(10), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    highlights = relationship(
        "Highlight",
        back_populates="book",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Highlight.created_at.asc()",
    )


class Highlight(Base):
    """Book highlight quote."""

    __tablename__ = "book_highlights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    page = Column(Integer, nullable=False, default=0)
    quote = Column(Text, nullable=False)
    memo = Column(Text, nullable=True)
    tags = Column(Text, nullable=False, default="[]")
    importance = Column(Integer, nullable=False, default=3)
    photo = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    book = relationship("Book", back_populates="highlights")


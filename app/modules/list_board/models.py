"""List Board 모듈 SQLAlchemy 모델."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class ListBoardItem(Base):
    """리스트 보드 아이템 (URL 기준 중복 방지)."""

    __tablename__ = "list_board_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    url = Column(String(2000), nullable=False, unique=True)
    duration_minutes = Column(Integer, nullable=True)
    source = Column(String(200), nullable=True)
    badge_type = Column(String(100), nullable=True)
    properties = Column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ListBoardColumn(Base):
    """리스트 보드 동적 컬럼 정의."""

    __tablename__ = "list_board_columns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), nullable=False, unique=True)
    display_name = Column(String(200), nullable=False)
    # checkbox | text | select | priority
    column_type = Column(String(50), nullable=False, default="text")
    options = Column(JSONB, nullable=False, default=list, server_default="[]")
    sort_order = Column(Integer, nullable=False, default=0)
    is_visible = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

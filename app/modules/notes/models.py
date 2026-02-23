"""Notes 모듈 SQLAlchemy 모델."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class NoteTagDef(Base):
    """태그 정의."""

    __tablename__ = "note_tag_defs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True)
    color = Column(String(7), nullable=False, default="#6b7280")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # relationships
    tags = relationship("NoteTag", back_populates="tag_def", cascade="all, delete-orphan")


class Note(Base):
    """활성 메모."""

    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False, default="")
    remark = Column(Text, nullable=True)
    is_pinned = Column(Integer, nullable=False, default=0)
    is_starred = Column(Integer, nullable=False, default=0)
    linked_menu_id = Column(String(50), nullable=True)
    linked_tab = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    # relationships
    tags = relationship(
        "NoteTag",
        primaryjoin="and_(NoteTag.note_id == Note.id, NoteTag.source == 'note')",
        foreign_keys="NoteTag.note_id",
        lazy="selectin",
    )
    histories = relationship(
        "NoteHistory",
        primaryjoin="and_(NoteHistory.note_id == Note.id, NoteHistory.source == 'note')",
        foreign_keys="NoteHistory.note_id",
        order_by="NoteHistory.changed_at.desc()",
        lazy="selectin",
    )


class NoteArchive(Base):
    """아카이브된 메모."""

    __tablename__ = "notes_archive"

    id = Column(Integer, primary_key=True, autoincrement=True)
    original_id = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False, default="")
    remark = Column(Text, nullable=True)
    linked_menu_id = Column(String(50), nullable=True)
    linked_tab = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    archived_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # relationships (viewonly: archive/restore는 서비스에서 직접 처리)
    tags = relationship(
        "NoteTag",
        primaryjoin="and_(NoteTag.note_id == NoteArchive.id, NoteTag.source == 'archive')",
        foreign_keys="NoteTag.note_id",
        lazy="selectin",
        viewonly=True,
        overlaps="tags",
    )
    histories = relationship(
        "NoteHistory",
        primaryjoin="and_(NoteHistory.note_id == NoteArchive.id, NoteHistory.source == 'archive')",
        foreign_keys="NoteHistory.note_id",
        order_by="NoteHistory.changed_at.desc()",
        lazy="selectin",
        viewonly=True,
        overlaps="histories",
    )


class NoteTag(Base):
    """메모-태그 연결 (notes + notes_archive 공용)."""

    __tablename__ = "note_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    note_id = Column(Integer, nullable=False)
    tag_id = Column(Integer, ForeignKey("note_tag_defs.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(10), nullable=False, default="note")

    # relationships
    tag_def = relationship("NoteTagDef", back_populates="tags")


class NoteHistory(Base):
    """메모 수정 이력 (다형성: source='note'|'archive')."""

    __tablename__ = "note_histories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    note_id = Column(Integer, nullable=False)  # FK 없음 (다형성)
    source = Column(String(10), nullable=False, default="note")
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False, default="")
    remark = Column(Text, nullable=True)
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

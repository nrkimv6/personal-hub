"""Notes 모듈 Pydantic 스키마."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


# ──────────────── Tag 스키마 ────────────────

class TagCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


class TagUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


class TagResponse(BaseModel):
    id: int
    name: str
    color: str
    note_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


# ──────────────── Note 스키마 ────────────────

class NoteTagInfo(BaseModel):
    id: int
    name: str
    color: str

    model_config = {"from_attributes": True}


class NoteCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(default="")
    remark: Optional[str] = None
    tag_ids: Optional[List[int]] = None
    linked_menu_id: Optional[str] = None
    linked_tab: Optional[str] = None


class NoteUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = None
    remark: Optional[str] = None
    tag_ids: Optional[List[int]] = None
    linked_menu_id: Optional[str] = None
    linked_tab: Optional[str] = None


class NoteResponse(BaseModel):
    id: int
    title: str
    content: str
    remark: Optional[str]
    is_pinned: bool
    is_starred: bool
    linked_menu_id: Optional[str] = None
    linked_tab: Optional[str] = None
    tags: List[NoteTagInfo] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NoteListResponse(BaseModel):
    items: List[NoteResponse]
    total: int
    page: int
    page_size: int
    pages: int


# ──────────────── Archive 스키마 ────────────────

class NoteArchiveResponse(BaseModel):
    id: int
    original_id: int
    title: str
    content: str
    remark: Optional[str]
    linked_menu_id: Optional[str] = None
    linked_tab: Optional[str] = None
    tags: List[NoteTagInfo] = []
    created_at: datetime
    updated_at: datetime
    archived_at: datetime

    model_config = {"from_attributes": True}


class ArchiveListResponse(BaseModel):
    items: List[NoteArchiveResponse]
    total: int
    page: int
    page_size: int
    pages: int


# ──────────────── Bulk 스키마 ────────────────

class BulkNoteIds(BaseModel):
    note_ids: List[int] = Field(..., min_length=1)


class BulkTagAction(BaseModel):
    note_ids: List[int] = Field(..., min_length=1)
    add_tag_ids: List[int] = []
    remove_tag_ids: List[int] = []


class BulkStarAction(BaseModel):
    note_ids: List[int] = Field(..., min_length=1)
    starred: bool


# ──────────────── History 스키마 ────────────────

class HistoryResponse(BaseModel):
    id: int
    title: str
    content: str
    remark: Optional[str]
    changed_at: datetime

    model_config = {"from_attributes": True}

"""List Board 모듈 Pydantic 스키마."""

import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, field_validator

COLUMN_TYPES = Literal["checkbox", "text", "select", "priority"]
_SLUG_RE = re.compile(r'^[a-z][a-z0-9_]{0,98}[a-z0-9]$|^[a-z]$')


class ColumnCreate(BaseModel):
    key: str
    display_name: str
    column_type: COLUMN_TYPES = "text"
    options: List[str] = []
    sort_order: int = 0

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError("key must be lowercase alphanumeric/underscore slug starting with a letter")
        return v


class ColumnUpdate(BaseModel):
    display_name: Optional[str] = None
    options: Optional[List[str]] = None
    sort_order: Optional[int] = None
    is_visible: Optional[bool] = None


class ColumnResponse(BaseModel):
    id: int
    key: str
    display_name: str
    column_type: str
    options: List[str]
    sort_order: int
    is_visible: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ItemPropertiesPatch(BaseModel):
    properties: Dict[str, Any]


class ListBoardItemResponse(BaseModel):
    id: int
    title: str
    url: str
    duration_minutes: Optional[int]
    source: Optional[str]
    badge_type: Optional[str]
    properties: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ListBoardListResponse(BaseModel):
    items: List[ListBoardItemResponse]
    total: int
    page: int
    page_size: int


class ListBoardImportRequest(BaseModel):
    markdown_text: str
    source: str
    badge_type: Optional[str] = None


class ListBoardItemImportResult(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: List[str]

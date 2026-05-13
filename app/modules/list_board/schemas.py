"""List Board 모듈 Pydantic 스키마."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


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

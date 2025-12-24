"""
UncategorizedPost 스키마 (Pydantic) - 미분류 게시물 관리
"""
import json
from pydantic import BaseModel, field_validator
from datetime import datetime, date
from typing import Optional, List, Literal


class UncategorizedBase(BaseModel):
    """UncategorizedPost 기본 스키마"""
    original_tag: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    organizer: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    urls: List[str] = []


class UncategorizedResponse(UncategorizedBase):
    """UncategorizedPost 응답 스키마"""
    id: int
    thumbnail_url: Optional[str] = None
    source_instagram_post_id: int
    source_instagram_url: Optional[str] = None
    source_instagram_account: Optional[str] = None
    reclassified_as: Optional[str] = None
    reclassified_id: Optional[int] = None
    reclassified_at: Optional[datetime] = None
    created_at: datetime

    @field_validator('urls', mode='before')
    @classmethod
    def parse_json_list(cls, v):
        """JSON 문자열을 리스트로 변환"""
        if v is None:
            return []
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return []
        return v

    class Config:
        from_attributes = True


class UncategorizedList(BaseModel):
    """UncategorizedPost 목록 응답"""
    items: List[UncategorizedResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ReclassifyRequest(BaseModel):
    """재분류 요청"""
    target: Literal["event", "popup"]
    title: Optional[str] = None  # 제목 재정의


class ReclassifyResponse(BaseModel):
    """재분류 응답"""
    success: bool
    target: str
    created_id: int
    message: str

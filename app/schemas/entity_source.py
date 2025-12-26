"""
EntitySource 스키마 (Pydantic) - 이벤트/팝업 다중 출처 관리
"""
import json
from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional, List, Literal, Any


class EntitySourceBase(BaseModel):
    """EntitySource 기본 스키마"""
    source_type: Literal["instagram", "web", "manual"]
    source_id: Optional[int] = None
    source_url: Optional[str] = None
    source_account: Optional[str] = None
    priority: int = 50
    contributed_fields: Optional[List[str]] = None
    extracted_data: Optional[dict] = None


class EntitySourceCreate(EntitySourceBase):
    """EntitySource 생성 스키마"""
    pass


class EntitySourceUpdate(BaseModel):
    """EntitySource 수정 스키마"""
    priority: Optional[int] = None
    contributed_fields: Optional[List[str]] = None


class EntitySourceResponse(EntitySourceBase):
    """EntitySource 응답 스키마"""
    id: int
    entity_type: Literal["event", "popup"]
    entity_id: int
    is_primary: bool = False
    discovered_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    @field_validator('contributed_fields', mode='before')
    @classmethod
    def parse_contributed_fields(cls, v):
        """JSON 문자열을 리스트로 변환"""
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v

    @field_validator('extracted_data', mode='before')
    @classmethod
    def parse_extracted_data(cls, v):
        """JSON 문자열을 dict로 변환"""
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v

    @field_validator('is_primary', mode='before')
    @classmethod
    def parse_is_primary(cls, v):
        """SQLite 정수를 bool로 변환"""
        if isinstance(v, int):
            return v == 1
        return bool(v) if v is not None else False

    class Config:
        from_attributes = True


class EntitySourceList(BaseModel):
    """EntitySource 목록 응답"""
    items: List[EntitySourceResponse]
    total: int
    entity_type: Literal["event", "popup"]
    entity_id: int

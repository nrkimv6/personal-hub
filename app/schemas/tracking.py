"""Pydantic schemas for Tracking APIs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


TrackingStatus = Literal["done", "overdue", "ready", "upcoming"]


class TrackingItemBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    start_at: datetime | None = None
    due_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title은 비어 있을 수 없습니다.")
        return stripped


class TrackingItemCreate(TrackingItemBase):
    @model_validator(mode="after")
    def require_start_or_due(self):
        if self.start_at is None and self.due_at is None:
            raise ValueError("start_at 또는 due_at 중 하나 이상이 필요합니다.")
        return self


class TrackingItemUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    start_at: datetime | None = None
    due_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def update_title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("title은 비어 있을 수 없습니다.")
        return stripped


class LinkedPlan(BaseModel):
    plan_record_id: int
    filename_hash: str
    title: str | None = None
    status: str | None = None
    file_path: str
    archived: bool
    file_removed: bool

    class Config:
        from_attributes = True


class TrackingItemResponse(BaseModel):
    id: int
    title: str
    description: str | None = None
    start_at: datetime | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    status: TrackingStatus
    linked_plans: list["LinkedPlan"] = []

    class Config:
        from_attributes = True


class LinkPlansRequest(BaseModel):
    plan_record_ids: list[int] = Field(default_factory=list, description="연결할 plan_record_id 목록")

    @field_validator("plan_record_ids")
    @classmethod
    def validate_ids(cls, v: list[int]) -> list[int]:
        for pid in v:
            if pid <= 0:
                raise ValueError(f"plan_record_id must be > 0, got {pid}")
        seen: set[int] = set()
        deduped = []
        for pid in v:
            if pid not in seen:
                seen.add(pid)
                deduped.append(pid)
        return deduped


class TrackingItemListResponse(BaseModel):
    items: list[TrackingItemResponse]
    total: int

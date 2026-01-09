"""Report schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ReportResponse(BaseModel):
    """보고서 응답 스키마."""

    id: int
    report_type: str
    period_start: datetime
    period_end: datetime
    title: Optional[str] = None
    content: str
    summary: Optional[str] = None
    statistics: Optional[str] = None
    llm_request_id: Optional[int] = None
    schedule_run_id: Optional[int] = None
    generated_at: datetime
    format: str = "markdown"

    class Config:
        from_attributes = True


class ReportListItem(BaseModel):
    """보고서 목록 아이템 스키마 (content 제외)."""

    id: int
    report_type: str
    period_start: datetime
    period_end: datetime
    title: Optional[str] = None
    summary: Optional[str] = None
    generated_at: datetime
    format: str

    class Config:
        from_attributes = True


class ReportList(BaseModel):
    """보고서 목록 응답."""

    items: list[ReportListItem]
    total: int
    page: int
    page_size: int
    total_pages: int

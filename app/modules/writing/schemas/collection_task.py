"""Writing 수집 작업(CollectionTask) 스키마."""

from datetime import datetime
from typing import Optional, Any, Dict
from uuid import UUID

from pydantic import BaseModel


class CollectionTaskResponse(BaseModel):
    """수집 작업 생성 응답 (202 Accepted)."""

    task_id: UUID
    type: str  # 'feeds_collect' | 'search_queries_collect' | 'wikisource_collect'
    status: str  # 'pending'
    created_at: datetime
    status_url: str  # 폴링 URL (예: /api/writing/feeds/collect/{task_id}/status)

    class Config:
        from_attributes = True


class CollectionStatusResponse(BaseModel):
    """수집 작업 상태 폴링 응답."""

    task_id: UUID
    type: str
    status: str  # 'pending' | 'running' | 'completed' | 'failed'

    # 진행 상황 (running 중 채워짐)
    progress: Optional[Dict[str, Any]] = None  # {"collected": 12, "total": 50, ...}

    # 최종 결과 (completed 시 채워짐)
    result: Optional[Dict[str, Any]] = None  # {"collected_count": 50, "skipped": 3, ...}

    # 오류 메시지 (failed 시 채워짐)
    error_message: Optional[str] = None

    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True

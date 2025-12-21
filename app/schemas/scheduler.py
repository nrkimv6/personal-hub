"""
스케줄러 관련 스키마
Windows 작업 스케줄러 관리 API용
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class ScheduledTaskResponse(BaseModel):
    """스케줄 작업 응답"""

    name: str
    folder: str
    status: str  # Ready, Running, Disabled
    last_run_time: Optional[datetime] = None
    last_result: Optional[int] = None  # 0=성공, 그 외=실패
    next_run_time: Optional[datetime] = None
    schedule: str  # "매일 00:10", "매주 일요일 03:00"
    enabled: bool


class ScheduledTaskListResponse(BaseModel):
    """작업 목록 응답"""

    tasks: List[ScheduledTaskResponse]
    total: int


class TaskUpdateRequest(BaseModel):
    """작업 상태 변경 요청"""

    enabled: bool


class TaskLogResponse(BaseModel):
    """작업 실행 로그 응답"""

    id: int
    task_name: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: str  # running, success, failed
    duration_seconds: Optional[int] = None
    records_processed: Optional[int] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class TaskLogListResponse(BaseModel):
    """로그 목록 응답"""

    logs: List[TaskLogResponse]
    total: int

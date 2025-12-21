"""
스케줄 작업 실행 로그 모델
Windows 작업 스케줄러 실행 이력 저장
"""
from sqlalchemy import Column, Integer, String, DateTime, Text
from app.models.base import Base


class ScheduledTaskLog(Base):
    """스케줄 작업 실행 로그"""

    __tablename__ = "scheduled_task_logs"

    id = Column(Integer, primary_key=True)
    task_name = Column(String(100), nullable=False, index=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime)
    status = Column(String(20), default="running")  # running, success, failed
    duration_seconds = Column(Integer)
    records_processed = Column(Integer)
    error_message = Column(Text)
    details = Column(Text)  # JSON 형식 추가 정보

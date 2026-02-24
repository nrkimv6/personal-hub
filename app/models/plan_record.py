"""
계획서 레코드 모델
계획서 메타데이터(메모, 이력)를 DB로 관리
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Index, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base


class PlanRecord(Base):
    """계획서 레코드 — 파일 기반 계획서의 메모/이력을 DB로 보완"""

    __tablename__ = "plan_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename_hash = Column(String, unique=True, nullable=False)  # sha256(생성시각+파일명)
    file_path = Column(String, nullable=False)                   # 현재 파일 경로 (캐시)
    project = Column(String)                                     # 프로젝트명
    title = Column(String)                                       # 계획서 제목
    status = Column(String)                                      # 상태
    memo = Column(Text)                                          # 확정 메모
    memo_draft = Column(Text)                                    # 임시저장 메모
    archived_at = Column(DateTime)                               # 아카이브 완료 시각
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    events = relationship("PlanEvent", back_populates="record", order_by="PlanEvent.created_at")

    __table_args__ = (
        Index("ix_plan_records_project", "project"),
        Index("ix_plan_records_status", "status"),
    )

    def __repr__(self):
        return f"<PlanRecord(id={self.id}, filename_hash={self.filename_hash[:8]}..., title={self.title})>"


class PlanEvent(Base):
    """계획서 이벤트 로그 — 타임라인 뷰 데이터 소스"""

    __tablename__ = "plan_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_record_id = Column(Integer, ForeignKey("plan_records.id"), nullable=False)
    event_type = Column(String, nullable=False)  # created, archived, status_changed, memo_updated, path_changed, missing
    detail = Column(JSON)                        # {"from": "초안", "to": "구현중"} 등
    created_at = Column(DateTime, default=datetime.now, index=True)

    record = relationship("PlanRecord", back_populates="events")

    __table_args__ = (
        Index("ix_plan_events_record_id", "plan_record_id"),
        Index("ix_plan_events_type", "event_type"),
    )

    def __repr__(self):
        return f"<PlanEvent(id={self.id}, event_type={self.event_type}, record_id={self.plan_record_id})>"

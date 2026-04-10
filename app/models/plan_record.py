"""
계획서 레코드 모델
계획서 메타데이터(메모, 이력)를 DB로 관리
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Index, ForeignKey, Date
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
    category = Column(String)                                    # 모듈 기반 분류 (naver-booking, instagram 등)
    tags = Column(JSON)                                          # 태그 목록 (feat, fix 등)
    summary = Column(Text)                                       # LLM 생성 요약
    superseded_by = Column(String)                               # 대체한 plan의 filename_hash
    intent = Column(Text, nullable=True)                         # 핵심 수정 의도 (LLM 추출)
    trigger = Column(String(50), nullable=True)                  # 작성 배경 (bug_recurrence|new_feature|refactor|ux_improvement|infra|unknown)
    scope = Column(Text, nullable=True)                          # 영향 범위 (JSON 직렬화 리스트)
    plan_date = Column(Date, nullable=True)                      # git 첫 커밋 날짜
    applied_at = Column(DateTime, nullable=True)                 # > 반영일: 헤더 파싱
    recurrence_count = Column(Integer, default=1, nullable=False)  # 체인 내 순서 (1=최초, 2=첫 재발, ...)
    chain_root_hash = Column(String(64), nullable=True)            # 체인 첫 번째 plan의 filename_hash
    recurrence_suggestion = Column(Text, nullable=True)            # LLM 생성 근본원인/개선 제안 (JSON)
    llm_processed_at = Column(DateTime)                          # LLM 분석 완료 시각
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    events = relationship("PlanEvent", back_populates="record", order_by="PlanEvent.created_at")

    __table_args__ = (
        Index("ix_plan_records_project", "project"),
        Index("ix_plan_records_status", "status"),
        Index("ix_plan_records_category", "category"),
    )

    def __repr__(self):
        return f"<PlanRecord(id={self.id}, filename_hash={self.filename_hash[:8]}..., title={self.title})>"


class PlanEvent(Base):
    """계획서 이벤트 로그 — 타임라인 뷰 데이터 소스"""

    __tablename__ = "plan_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_record_id = Column(Integer, ForeignKey("plan_records.id"), nullable=True)  # nullable: 시스템 이벤트(devguide_staleness) 허용
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

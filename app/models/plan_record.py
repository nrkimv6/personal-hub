"""
계획서 레코드 모델
계획서 메타데이터(메모, 이력)를 DB로 관리
"""
from datetime import datetime
from sqlalchemy import Boolean, Column, Integer, String, DateTime, Text, JSON, Index, ForeignKey, Date, UniqueConstraint
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
    claude_session_id = Column(String(36), nullable=True)         # dev-runner 발급 UUID (CLI --session-id와 동일)
    raw_content = Column(Text, nullable=True)                     # archive 파일 본문 전체 (DB-first 진실원본)
    file_delete_after = Column(DateTime, nullable=True)           # LLM 분석 성공 후 archive 파일 삭제 예정 시각
    file_removed_at = Column(DateTime, nullable=True)             # archive 파일이 실제 working copy에서 제거된 시각
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    events = relationship("PlanEvent", back_populates="record", order_by="PlanEvent.created_at")
    tracking_links = relationship("TrackingItemPlanLink", back_populates="plan_record", lazy="select", cascade="all, delete-orphan")
    chunks = relationship("PlanRecordChunk", back_populates="record", cascade="all, delete-orphan")
    file_refs = relationship("PlanRecordFileRef", back_populates="record", cascade="all, delete-orphan")
    repo_refs = relationship("PlanRecordRepoRef", back_populates="record", cascade="all, delete-orphan")
    outgoing_relations = relationship(
        "PlanRecordRelation",
        foreign_keys="PlanRecordRelation.source_plan_record_id",
        back_populates="source_record",
        cascade="all, delete-orphan",
    )
    incoming_relations = relationship(
        "PlanRecordRelation",
        foreign_keys="PlanRecordRelation.target_plan_record_id",
        back_populates="target_record",
        cascade="all, delete-orphan",
    )

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


class PlanRecordChunk(Base):
    """Archived plan evidence chunk for retrieval."""

    __tablename__ = "plan_record_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_record_id = Column(Integer, ForeignKey("plan_records.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    section_type = Column(String(50), nullable=False, default="body")
    heading = Column(String(500), nullable=True)
    text = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    token_estimate = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    record = relationship("PlanRecord", back_populates="chunks")
    embedding_records = relationship("PlanRecordChunkEmbedding", back_populates="chunk", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("plan_record_id", "chunk_index", name="uq_plan_record_chunk_index"),
        Index("ix_plan_record_chunks_record", "plan_record_id"),
        Index("ix_plan_record_chunks_section", "section_type"),
        Index("ix_plan_record_chunks_hash", "content_hash"),
    )


class PlanRecordChunkEmbedding(Base):
    """Semantic embedding for one retrieval chunk and one provider/model config."""

    __tablename__ = "plan_record_chunk_embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chunk_id = Column(Integer, ForeignKey("plan_record_chunks.id", ondelete="CASCADE"), nullable=False)
    plan_record_id = Column(Integer, ForeignKey("plan_records.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(80), nullable=False)
    model = Column(String(160), nullable=False)
    dimension = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    vector = Column(JSON, nullable=False)
    status = Column(String(30), nullable=False, default="completed")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    chunk = relationship("PlanRecordChunk", back_populates="embedding_records")
    record = relationship("PlanRecord")

    __table_args__ = (
        UniqueConstraint(
            "chunk_id",
            "provider",
            "model",
            "dimension",
            "content_hash",
            name="uq_plan_record_chunk_embedding_config_hash",
        ),
        Index("ix_plan_record_chunk_embeddings_chunk", "chunk_id"),
        Index("ix_plan_record_chunk_embeddings_record", "plan_record_id"),
        Index("ix_plan_record_chunk_embeddings_config", "provider", "model", "dimension"),
        Index("ix_plan_record_chunk_embeddings_status", "status"),
    )


class PlanRecordFileRef(Base):
    """File reference mentioned by a plan or derived from git changes."""

    __tablename__ = "plan_record_file_refs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_record_id = Column(Integer, ForeignKey("plan_records.id", ondelete="CASCADE"), nullable=False)
    chunk_id = Column(Integer, ForeignKey("plan_record_chunks.id", ondelete="SET NULL"), nullable=True)
    source_type = Column(String(50), nullable=False)
    path = Column(String(1000), nullable=False)
    module = Column(String(200), nullable=True)
    change_type = Column(String(20), nullable=True)
    commit_sha = Column(String(64), nullable=True)
    repo_key = Column(String(100), nullable=False, default="monitor-page")
    repo_root = Column(String(1000), nullable=True)
    repo_commit_sha = Column(String(64), nullable=True)
    commit_date = Column(DateTime, nullable=True)
    lines_added = Column(Integer, nullable=True)
    lines_deleted = Column(Integer, nullable=True)
    evidence = Column(Text, nullable=True)
    exists_at_index = Column(Boolean, nullable=False, default=False)
    first_seen_at = Column(DateTime, default=datetime.now)
    last_seen_at = Column(DateTime, default=datetime.now)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    record = relationship("PlanRecord", back_populates="file_refs")
    chunk = relationship("PlanRecordChunk")

    __table_args__ = (
        UniqueConstraint(
            "plan_record_id",
            "repo_key",
            "source_type",
            "path",
            "commit_sha",
            name="uq_plan_record_file_ref_source",
        ),
        Index("ix_plan_record_file_refs_record", "plan_record_id"),
        Index("ix_plan_record_file_refs_repo", "repo_key"),
        Index("ix_plan_record_file_refs_path", "path"),
        Index("ix_plan_record_file_refs_source", "source_type"),
        Index("ix_plan_record_file_refs_module", "module"),
    )


class PlanRecordRepoRef(Base):
    """Repository touched by, or indexed for, an archived plan."""

    __tablename__ = "plan_record_repo_refs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_record_id = Column(Integer, ForeignKey("plan_records.id", ondelete="CASCADE"), nullable=False)
    repo_key = Column(String(100), nullable=False)
    repo_root = Column(String(1000), nullable=True)
    repo_commit_sha = Column(String(64), nullable=True)
    source_type = Column(String(50), nullable=False, default="git_changed")
    status = Column(String(30), nullable=False, default="ready")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    record = relationship("PlanRecord", back_populates="repo_refs")

    __table_args__ = (
        UniqueConstraint("plan_record_id", "repo_key", "source_type", name="uq_plan_record_repo_ref_source"),
        Index("ix_plan_record_repo_refs_record", "plan_record_id"),
        Index("ix_plan_record_repo_refs_repo", "repo_key"),
        Index("ix_plan_record_repo_refs_status", "status"),
    )


class PlanRecordRelation(Base):
    """Derived relation between archived plans."""

    __tablename__ = "plan_record_relations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_plan_record_id = Column(Integer, ForeignKey("plan_records.id", ondelete="CASCADE"), nullable=False)
    target_plan_record_id = Column(Integer, ForeignKey("plan_records.id", ondelete="CASCADE"), nullable=False)
    relation_type = Column(String(50), nullable=False)
    score = Column(Integer, nullable=False, default=0)
    evidence = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    source_record = relationship("PlanRecord", foreign_keys=[source_plan_record_id], back_populates="outgoing_relations")
    target_record = relationship("PlanRecord", foreign_keys=[target_plan_record_id], back_populates="incoming_relations")

    __table_args__ = (
        UniqueConstraint(
            "source_plan_record_id",
            "target_plan_record_id",
            "relation_type",
            name="uq_plan_record_relation",
        ),
        Index("ix_plan_record_relations_source", "source_plan_record_id"),
        Index("ix_plan_record_relations_target", "target_plan_record_id"),
        Index("ix_plan_record_relations_type", "relation_type"),
    )


class PlanRecordSearchRun(Base):
    """Backfill/index execution audit row."""

    __tablename__ = "plan_record_search_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_record_id = Column(Integer, ForeignKey("plan_records.id", ondelete="SET NULL"), nullable=True)
    run_type = Column(String(50), nullable=False, default="index")
    status = Column(String(30), nullable=False, default="pending")
    dry_run = Column(Boolean, nullable=False, default=True)
    force = Column(Boolean, nullable=False, default=False)
    indexed_count = Column(Integer, nullable=False, default=0)
    skipped_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    detail = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime, nullable=True)

    record = relationship("PlanRecord")

    __table_args__ = (
        Index("ix_plan_record_search_runs_record", "plan_record_id"),
        Index("ix_plan_record_search_runs_status", "status"),
        Index("ix_plan_record_search_runs_started", "started_at"),
    )

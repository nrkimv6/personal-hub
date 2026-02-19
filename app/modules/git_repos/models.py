"""Git Repository 관련 SQLAlchemy 모델."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class GitRepo(Base):
    """등록된 Git 레포지토리."""
    __tablename__ = "git_repos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(String, nullable=False, unique=True)         # 절대 경로
    alias = Column(String, nullable=True)                       # 표시 이름
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)

    # 마지막 상태 캐시
    last_status = Column(String, nullable=True)                 # "clean" | "dirty" | "conflict" | "unknown"
    last_branch = Column(String, nullable=True)
    last_ahead = Column(Integer, nullable=True)
    last_behind = Column(Integer, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 관계
    operation_logs = relationship(
        "GitOperationLog",
        back_populates="repo",
        cascade="all, delete-orphan",
        order_by="GitOperationLog.created_at.desc()"
    )


class GitOperationLog(Base):
    """Git 작업 이력 로그."""
    __tablename__ = "git_operation_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(Integer, ForeignKey("git_repos.id", ondelete="CASCADE"), nullable=False)
    operation = Column(String, nullable=False)    # "commit" | "push" | "pull" | "fetch" | "stash" | "stash_pop"
    status = Column(String, nullable=False)       # "success" | "failure"
    message = Column(Text, nullable=True)          # 커밋 메시지 or 오류 요약
    detail = Column(Text, nullable=True)           # stdout / stderr 전문
    created_at = Column(DateTime, default=datetime.now)

    # 관계
    repo = relationship("GitRepo", back_populates="operation_logs")

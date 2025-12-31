"""Writing SQLAlchemy Models - 글쓰기 소스 및 생성된 글."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from .base import Base


class WritingSource(Base):
    """글쓰기 소스 (원본 글)."""

    __tablename__ = "writing_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)  # 글 본문
    category = Column(String(50), nullable=True)  # 분류 (선택)
    source_info = Column(String(200), nullable=True)  # 출처 정보

    created_at = Column(DateTime, default=datetime.now)

    def __repr__(self):
        return f"<WritingSource(id={self.id}, category={self.category})>"


class GeneratedWriting(Base):
    """생성된 글."""

    __tablename__ = "generated_writings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 생성 정보
    task_type = Column(String(20), nullable=False)  # 'mix' or 'random'
    prompt_used = Column(Text, nullable=True)  # 사용된 프롬프트
    source_ids = Column(String(100), nullable=True)  # 사용된 소스 ID들 (예: "1,5,23")

    # 결과
    content = Column(Text, nullable=False)  # 생성된 글
    raw_response = Column(Text, nullable=True)  # LLM 전체 응답
    selected_elements = Column(Text, nullable=True)  # 선택된 요소 JSON

    # 평가
    rating = Column(Integer, nullable=True)  # 1: 추천, -1: 비추천, NULL: 미평가

    # 메타
    schedule_run_id = Column(
        Integer, ForeignKey("crawl_schedule_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    deleted_at = Column(DateTime, nullable=True, index=True)  # soft delete

    # 상수
    TASK_TYPE_MIX = "mix"  # 3개 글 믹스
    TASK_TYPE_RANDOM = "random"  # 랜덤 프롬프트

    RATING_LIKE = 1
    RATING_DISLIKE = -1

    def __repr__(self):
        return f"<GeneratedWriting(id={self.id}, task_type={self.task_type})>"

    def get_source_id_list(self) -> list[int]:
        """source_ids를 int 리스트로 반환."""
        if not self.source_ids:
            return []
        return [int(x) for x in self.source_ids.split(",") if x]

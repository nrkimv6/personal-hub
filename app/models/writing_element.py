"""Writing Element Models - 글쓰기 요소 및 사용 이력."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base


class WritingElement(Base):
    """글쓰기 요소 마스터.

    소재, 키워드, 톤, 문체, 형식, 감정선 등을 관리.
    """

    __tablename__ = "writing_elements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(20), nullable=False)  # 카테고리
    name = Column(String(100), nullable=False)  # 요소 이름
    season_hint = Column(String(50), nullable=True)  # 시즌 힌트 (쉼표 구분)
    is_active = Column(Integer, default=1)  # 활성화 여부

    # 빈도 기반 키워드용 (keyword_stats에서 승격된 경우)
    frequency = Column(Integer, nullable=True)  # 빈도수
    source_keyword_id = Column(Integer, nullable=True)  # 원본 keyword_stats.id

    # 소스 타입 (seed: 시드, auto: 자동추출, manual: 수동)
    source_type = Column(String(20), default="seed")

    created_at = Column(DateTime, default=datetime.now)

    # 소스 타입 상수
    SOURCE_TYPE_SEED = "seed"
    SOURCE_TYPE_AUTO = "auto"
    SOURCE_TYPE_MANUAL = "manual"

    # 카테고리 상수
    CATEGORY_TOPIC = "topic"  # 소재
    CATEGORY_KEYWORD = "keyword"  # 키워드
    CATEGORY_TONE = "tone"  # 톤
    CATEGORY_STYLE = "style"  # 문체
    CATEGORY_FORMAT = "format"  # 형식
    CATEGORY_EMOTION = "emotion"  # 감정선

    ALL_CATEGORIES = [
        CATEGORY_TOPIC,
        CATEGORY_KEYWORD,
        CATEGORY_TONE,
        CATEGORY_STYLE,
        CATEGORY_FORMAT,
        CATEGORY_EMOTION,
    ]

    # 시즌 상수
    SEASON_SPRING = "spring"
    SEASON_SUMMER = "summer"
    SEASON_FALL = "fall"
    SEASON_WINTER = "winter"
    SEASON_CHUSEOK = "chuseok"
    SEASON_PARENTS_DAY = "parents_day"

    def __repr__(self):
        return f"<WritingElement(id={self.id}, category={self.category}, name={self.name})>"

    def get_season_hints(self) -> list[str]:
        """시즌 힌트를 리스트로 반환."""
        if not self.season_hint:
            return []
        return [s.strip() for s in self.season_hint.split(",") if s.strip()]

    def matches_season(self, season: str) -> bool:
        """주어진 시즌과 매칭되는지 확인."""
        return season in self.get_season_hints()


class WritingElementUsage(Base):
    """글쓰기 요소/소스 사용 이력.

    요소 또는 소스가 언제 사용되었는지 추적.
    """

    __tablename__ = "writing_element_usages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    element_id = Column(
        Integer, ForeignKey("writing_elements.id", ondelete="CASCADE"), nullable=True
    )
    source_id = Column(
        Integer, ForeignKey("writing_sources.id", ondelete="CASCADE"), nullable=True
    )
    generated_writing_id = Column(
        Integer, ForeignKey("generated_writings.id", ondelete="CASCADE"), nullable=False
    )
    used_at = Column(DateTime, default=datetime.now, index=True)

    # Relationships
    element = relationship("WritingElement", backref="usages")
    source = relationship("WritingSource", backref="usages")
    generated_writing = relationship("GeneratedWriting", backref="element_usages")

    def __repr__(self):
        if self.element_id:
            return f"<WritingElementUsage(element_id={self.element_id}, writing_id={self.generated_writing_id})>"
        return f"<WritingElementUsage(source_id={self.source_id}, writing_id={self.generated_writing_id})>"

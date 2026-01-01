"""Keyword Stats SQLAlchemy Model - 키워드 빈도 통계."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base


class KeywordStats(Base):
    """키워드 빈도 통계.

    글소스에서 Kiwi 형태소 분석으로 추출된 키워드 통계.
    """

    __tablename__ = "keyword_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    keyword = Column(Text, nullable=False)
    frequency = Column(Integer, nullable=False, default=1)  # 총 출현 횟수
    source_count = Column(Integer, nullable=False, default=1)  # 키워드가 나온 글 개수
    avg_per_source = Column(Float)  # 글당 평균 출현

    # 카테고리별 분석용
    category = Column(Text, nullable=True)

    # 관리 상태
    is_stopword = Column(Integer, default=0)  # 불용어 여부
    is_promoted = Column(Integer, default=0)  # writing_elements로 승격됨
    element_id = Column(
        Integer, ForeignKey("writing_elements.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at = Column(DateTime, nullable=True)  # 검토 일시

    analyzed_at = Column(DateTime, default=datetime.now)

    # Relationships
    element = relationship("WritingElement", backref="source_keywords")

    def __repr__(self):
        return f"<KeywordStats(id={self.id}, keyword={self.keyword}, frequency={self.frequency})>"

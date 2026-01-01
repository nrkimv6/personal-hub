"""Writing Stopword SQLAlchemy Model - 키워드 추출 제외 불용어."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from .base import Base


class WritingStopword(Base):
    """키워드 추출 시 제외할 불용어.

    블로그 템플릿/UI 요소, 일반 불용어 등을 관리.
    """

    __tablename__ = "writing_stopwords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    word = Column(Text, nullable=False, unique=True)
    category = Column(String(20), default="general")  # 'template', 'ui', 'general'
    created_at = Column(DateTime, default=datetime.now)

    # 카테고리 상수
    CATEGORY_TEMPLATE = "template"  # 블로그 템플릿 관련
    CATEGORY_UI = "ui"  # UI 요소
    CATEGORY_GENERAL = "general"  # 일반 불용어
    CATEGORY_REVIEWED = "reviewed"  # 검토 후 추가된 불용어

    def __repr__(self):
        return f"<WritingStopword(id={self.id}, word={self.word}, category={self.category})>"

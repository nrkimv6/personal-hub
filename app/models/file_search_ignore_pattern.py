"""FileSearchIgnorePattern SQLAlchemy Model - 파일 검색 무시 패턴."""

from sqlalchemy import Column, Integer, Text
from datetime import datetime

from .base import Base


class FileSearchIgnorePattern(Base):
    """파일 검색 무시 패턴 모델.

    node_modules, .git 등 검색 결과에서 제외할 디렉토리/파일 패턴을 관리.
    enabled=1인 패턴은 검색 시 자동으로 excludes에 병합됨.
    """

    __tablename__ = "file_search_ignore_pattern"

    id = Column(Integer, primary_key=True, autoincrement=True)
    label = Column(Text, nullable=False)
    pattern = Column(Text, nullable=False)
    enabled = Column(Integer, nullable=False, default=1)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(Text, nullable=False, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def __repr__(self):
        return (
            f"<FileSearchIgnorePattern(id={self.id}, label={self.label!r}, "
            f"pattern={self.pattern!r}, enabled={self.enabled})>"
        )

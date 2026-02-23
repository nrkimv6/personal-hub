"""FileSearchStatus SQLAlchemy Model - Everything/ripgrep 상태 캐시."""

from sqlalchemy import Column, Integer, Boolean, Text, String
from datetime import datetime

from .base import Base


class FileSearchStatus(Base):
    """파일 검색 도구 상태 캐시 모델.

    FileSearchWorker가 30초마다 Everything/ripgrep 상태를 체크하고 이 테이블에 캐싱.
    API의 GET /status는 이 테이블을 즉시 조회 (Session 0에서 직접 체크 불가).

    단일 행 패턴: 항상 id=1 행만 유지하여 UPSERT 방식으로 갱신.
    """

    __tablename__ = "file_search_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    everything_ok = Column(Boolean, nullable=False, default=False)
    ripgrep_ok = Column(Boolean, nullable=False, default=False)
    ripgrep_path = Column(Text, nullable=True)
    checked_at = Column(String(30), nullable=False, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def __repr__(self):
        return (
            f"<FileSearchStatus(everything_ok={self.everything_ok}, "
            f"ripgrep_ok={self.ripgrep_ok}, checked_at={self.checked_at})>"
        )

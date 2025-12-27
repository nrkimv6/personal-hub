"""
BrowserProfile 모델 - 브라우저 프로필 (Playwright 컨텍스트 단위)
"""
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.service_account import ServiceAccount


class BrowserProfile(Base):
    """브라우저 프로필 (Playwright 컨텍스트 단위)"""
    __tablename__ = "browser_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 프로필 식별
    name = Column(String(100), nullable=False)  # 프로필명 ("메인", "서브1")
    profile_dir = Column(String(100), unique=True, nullable=False)  # 브라우저 프로필 디렉토리

    # 상태
    is_active = Column(Boolean, default=True)  # 활성화 여부

    # 메타
    description = Column(Text, nullable=True)  # 설명
    last_used_at = Column(DateTime, nullable=True)  # 마지막 사용 시간
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 관계
    service_accounts = relationship(
        "ServiceAccount",
        back_populates="profile",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<BrowserProfile(id={self.id}, name={self.name}, profile_dir={self.profile_dir})>"

    @property
    def profile_path(self) -> str:
        """프로필의 전체 경로 반환"""
        from pathlib import Path
        from app.config import settings
        return str(Path(settings.DATA_DIR) / "browser_profiles" / self.profile_dir)

    def get_account(self, service_type: str) -> Optional["ServiceAccount"]:
        """특정 서비스 계정 조회"""
        for account in self.service_accounts:
            if account.service_type == service_type:
                return account
        return None

    @property
    def naver_account(self) -> Optional["ServiceAccount"]:
        """네이버 계정"""
        return self.get_account("naver")

    @property
    def instagram_account(self) -> Optional["ServiceAccount"]:
        """인스타그램 계정"""
        return self.get_account("instagram")

    @property
    def coupang_account(self) -> Optional["ServiceAccount"]:
        """쿠팡 계정"""
        return self.get_account("coupang")

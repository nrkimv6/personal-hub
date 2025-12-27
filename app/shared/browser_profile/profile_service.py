"""
BrowserProfile 서비스 - 브라우저 프로필 관리 CRUD
"""
from pathlib import Path
from typing import List, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.browser_profile import BrowserProfile
from app.schemas.browser_profile import BrowserProfileCreate, BrowserProfileUpdate
from app.core.config import settings, logger


class BrowserProfileService:
    """브라우저 프로필 관리 서비스"""

    def get_all(self, db: Session, include_inactive: bool = False) -> List[BrowserProfile]:
        """전체 프로필 목록 조회"""
        query = db.query(BrowserProfile)
        if not include_inactive:
            query = query.filter(BrowserProfile.is_active == True)
        return query.order_by(BrowserProfile.name).all()

    def get_by_id(self, db: Session, profile_id: int) -> Optional[BrowserProfile]:
        """ID로 프로필 조회"""
        return db.query(BrowserProfile).filter(BrowserProfile.id == profile_id).first()

    def get_by_name(self, db: Session, name: str) -> Optional[BrowserProfile]:
        """이름으로 프로필 조회"""
        return db.query(BrowserProfile).filter(BrowserProfile.name == name).first()

    def get_by_profile_dir(self, db: Session, profile_dir: str) -> Optional[BrowserProfile]:
        """프로필 디렉토리로 프로필 조회"""
        return db.query(BrowserProfile).filter(BrowserProfile.profile_dir == profile_dir).first()

    def create(self, db: Session, data: BrowserProfileCreate) -> BrowserProfile:
        """프로필 생성"""
        # 프로필 디렉토리 생성
        profile_path = Path(settings.DATA_DIR) / "browser_profiles" / data.profile_dir
        if not profile_path.exists():
            profile_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"프로필 디렉토리 생성: {profile_path}")

        profile = BrowserProfile(
            name=data.name,
            profile_dir=data.profile_dir,
            is_active=data.is_active,
            description=data.description,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        logger.info(f"프로필 생성: {profile.name} (profile_dir={profile.profile_dir})")
        return profile

    def update(self, db: Session, profile_id: int, data: BrowserProfileUpdate) -> Optional[BrowserProfile]:
        """프로필 수정"""
        profile = self.get_by_id(db, profile_id)
        if not profile:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(profile, key, value)

        profile.updated_at = datetime.now()
        db.commit()
        db.refresh(profile)
        logger.info(f"프로필 수정: {profile.name} (id={profile_id})")
        return profile

    def delete(self, db: Session, profile_id: int, remove_browser_data: bool = False) -> bool:
        """
        프로필 삭제

        Args:
            db: 데이터베이스 세션
            profile_id: 프로필 ID
            remove_browser_data: True일 경우 브라우저 데이터 디렉토리도 삭제
        """
        profile = self.get_by_id(db, profile_id)
        if not profile:
            return False

        profile_dir = profile.profile_dir

        # DB에서 삭제 (cascade로 service_accounts도 삭제됨)
        db.delete(profile)
        db.commit()
        logger.info(f"프로필 삭제: {profile.name} (id={profile_id})")

        # 브라우저 데이터 디렉토리 삭제 옵션
        if remove_browser_data:
            profile_path = Path(settings.DATA_DIR) / "browser_profiles" / profile_dir
            if profile_path.exists():
                import shutil
                shutil.rmtree(profile_path)
                logger.info(f"프로필 디렉토리 삭제: {profile_path}")

        return True

    def update_last_used(self, db: Session, profile_id: int) -> Optional[BrowserProfile]:
        """마지막 사용 시간 업데이트"""
        profile = self.get_by_id(db, profile_id)
        if not profile:
            return None

        profile.last_used_at = datetime.now()
        profile.updated_at = datetime.now()
        db.commit()
        db.refresh(profile)
        return profile

    def get_default_profile(self, db: Session) -> Optional[BrowserProfile]:
        """기본 프로필 조회 (profile_dir='default')"""
        return self.get_by_profile_dir(db, "default")

    def get_active_profiles(self, db: Session) -> List[BrowserProfile]:
        """활성화된 프로필 목록 조회"""
        return db.query(BrowserProfile).filter(BrowserProfile.is_active == True).order_by(BrowserProfile.name).all()


# 싱글톤 인스턴스
browser_profile_service = BrowserProfileService()

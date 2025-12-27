"""
Account 서비스 - 계정(프로필) 관리 CRUD
다중 프로필 지원을 위한 계정 관리
"""
import os
from pathlib import Path
from typing import List, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.account import Account
from app.schemas.account import AccountCreate, AccountUpdate
from app.core.config import settings, logger


class AccountService:
    """계정 관리 서비스"""

    def get_all(self, db: Session, include_inactive: bool = False) -> List[Account]:
        """전체 계정 목록 조회"""
        query = db.query(Account)
        if not include_inactive:
            query = query.filter(Account.is_active == True)
        return query.order_by(Account.name).all()

    def get_by_id(self, db: Session, service_account_id: int) -> Optional[Account]:
        """ID로 계정 조회"""
        return db.query(Account).filter(Account.id == service_account_id).first()

    def get_by_name(self, db: Session, name: str) -> Optional[Account]:
        """이름으로 계정 조회"""
        return db.query(Account).filter(Account.name == name).first()

    def get_by_profile_dir(self, db: Session, profile_dir: str) -> Optional[Account]:
        """프로필 디렉토리로 계정 조회"""
        return db.query(Account).filter(Account.profile_dir == profile_dir).first()

    def create(self, db: Session, data: AccountCreate) -> Account:
        """계정 생성"""
        # 프로필 디렉토리 생성
        profile_path = Path(settings.DATA_DIR) / "browser_profiles" / data.profile_dir
        if not profile_path.exists():
            profile_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"프로필 디렉토리 생성: {profile_path}")

        # booking_info 처리 (Pydantic 객체 → dict)
        booking_info_dict = None
        if hasattr(data, 'booking_info') and data.booking_info is not None:
            if hasattr(data.booking_info, 'model_dump'):
                booking_info_dict = data.booking_info.model_dump(exclude_none=True)
            else:
                booking_info_dict = data.booking_info

        account = Account(
            name=data.name,
            email=data.email,
            profile_dir=data.profile_dir,
            is_active=data.is_active,
            description=data.description,
        )
        # booking_info는 property setter를 통해 JSON 문자열로 변환됨
        if booking_info_dict:
            account.booking_info = booking_info_dict
        db.add(account)
        db.commit()
        db.refresh(account)
        logger.info(f"계정 생성: {account.name} (profile_dir={account.profile_dir})")
        return account

    def update(self, db: Session, service_account_id: int, data: AccountUpdate) -> Optional[Account]:
        """계정 수정"""
        account = self.get_by_id(db, service_account_id)
        if not account:
            return None

        update_data = data.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            # booking_info는 Pydantic 객체 → dict 변환 필요
            if key == 'booking_info' and value is not None:
                # Pydantic 객체인 경우 dict로 변환
                if hasattr(value, 'model_dump'):
                    value = value.model_dump(exclude_none=True)
            setattr(account, key, value)

        account.updated_at = datetime.now()
        db.commit()
        db.refresh(account)
        logger.info(f"계정 수정: {account.name} (id={service_account_id})")
        return account

    def delete(self, db: Session, service_account_id: int, remove_profile: bool = False) -> bool:
        """
        계정 삭제

        Args:
            db: 데이터베이스 세션
            service_account_id: 계정 ID
            remove_profile: True일 경우 프로필 디렉토리도 삭제
        """
        account = self.get_by_id(db, service_account_id)
        if not account:
            return False

        profile_dir = account.profile_dir

        # DB에서 삭제
        db.delete(account)
        db.commit()
        logger.info(f"계정 삭제: {account.name} (id={service_account_id})")

        # 프로필 디렉토리 삭제 옵션
        if remove_profile:
            profile_path = Path(settings.DATA_DIR) / "browser_profiles" / profile_dir
            if profile_path.exists():
                import shutil
                shutil.rmtree(profile_path)
                logger.info(f"프로필 디렉토리 삭제: {profile_path}")

        return True

    def update_login_status(self, db: Session, service_account_id: int, is_logged_in: bool) -> Optional[Account]:
        """로그인 상태 업데이트"""
        account = self.get_by_id(db, service_account_id)
        if not account:
            return None

        account.is_logged_in = is_logged_in
        account.updated_at = datetime.now()
        db.commit()
        db.refresh(account)
        logger.info(f"계정 로그인 상태 업데이트: {account.name} -> {is_logged_in}")
        return account

    def update_last_used(self, db: Session, service_account_id: int) -> Optional[Account]:
        """마지막 사용 시간 업데이트"""
        account = self.get_by_id(db, service_account_id)
        if not account:
            return None

        account.last_used_at = datetime.now()
        account.updated_at = datetime.now()
        db.commit()
        db.refresh(account)
        return account

    def get_default_account(self, db: Session) -> Optional[Account]:
        """기본 계정 조회 (profile_dir='default')"""
        return self.get_by_profile_dir(db, "default")

    def get_active_accounts(self, db: Session) -> List[Account]:
        """활성화된 계정 목록 조회"""
        return db.query(Account).filter(Account.is_active == True).order_by(Account.name).all()


# 싱글톤 인스턴스
account_service = AccountService()

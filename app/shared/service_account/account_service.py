"""
ServiceAccount 서비스 - 서비스별 계정 관리 CRUD
"""
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session, joinedload
from datetime import datetime

from app.models.service_account import ServiceAccount
from app.models.browser_profile import BrowserProfile
from app.schemas.service_account import ServiceAccountCreate, ServiceAccountUpdate
from app.core.config import logger


class ServiceAccountService:
    """서비스 계정 관리 서비스"""

    def get_all(self, db: Session) -> List[ServiceAccount]:
        """전체 서비스 계정 목록 조회"""
        return db.query(ServiceAccount).options(
            joinedload(ServiceAccount.profile)
        ).order_by(ServiceAccount.profile_id, ServiceAccount.service_type).all()

    def get_by_id(self, db: Session, account_id: int) -> Optional[ServiceAccount]:
        """ID로 서비스 계정 조회"""
        return db.query(ServiceAccount).options(
            joinedload(ServiceAccount.profile)
        ).filter(ServiceAccount.id == account_id).first()

    def get_by_profile_id(self, db: Session, profile_id: int) -> List[ServiceAccount]:
        """프로필 ID로 서비스 계정 목록 조회"""
        return db.query(ServiceAccount).filter(
            ServiceAccount.profile_id == profile_id
        ).order_by(ServiceAccount.service_type).all()

    def get_by_profile_and_type(
        self,
        db: Session,
        profile_id: int,
        service_type: str
    ) -> Optional[ServiceAccount]:
        """프로필 ID + 서비스 타입으로 조회"""
        return db.query(ServiceAccount).filter(
            ServiceAccount.profile_id == profile_id,
            ServiceAccount.service_type == service_type
        ).first()

    def get_all_by_service_type(self, db: Session, service_type: str) -> List[ServiceAccount]:
        """특정 서비스 타입의 모든 계정 조회"""
        return db.query(ServiceAccount).options(
            joinedload(ServiceAccount.profile)
        ).filter(
            ServiceAccount.service_type == service_type
        ).order_by(ServiceAccount.profile_id).all()

    def get_logged_in_accounts(self, db: Session, service_type: str) -> List[ServiceAccount]:
        """로그인된 계정만 조회"""
        return db.query(ServiceAccount).options(
            joinedload(ServiceAccount.profile)
        ).filter(
            ServiceAccount.service_type == service_type,
            ServiceAccount.is_logged_in == True
        ).order_by(ServiceAccount.profile_id).all()

    def get_active_accounts_by_type(self, db: Session, service_type: str) -> List[ServiceAccount]:
        """활성 프로필의 특정 서비스 계정 조회"""
        return db.query(ServiceAccount).join(
            BrowserProfile
        ).filter(
            ServiceAccount.service_type == service_type,
            BrowserProfile.is_active == True
        ).order_by(BrowserProfile.name).all()

    def create(
        self,
        db: Session,
        profile_id: int,
        data: ServiceAccountCreate
    ) -> ServiceAccount:
        """서비스 계정 생성"""
        # 프로필 존재 확인
        profile = db.query(BrowserProfile).filter(BrowserProfile.id == profile_id).first()
        if not profile:
            raise ValueError(f"Profile not found: {profile_id}")

        # 동일 프로필+서비스 타입 중복 확인
        existing = self.get_by_profile_and_type(db, profile_id, data.service_type)
        if existing:
            raise ValueError(f"Service account already exists: profile_id={profile_id}, service_type={data.service_type}")

        # credentials 처리
        credentials_dict = None
        if data.credentials:
            credentials_dict = data.credentials

        account = ServiceAccount(
            profile_id=profile_id,
            service_type=data.service_type,
            identifier=data.identifier,
            password=data.password,  # TODO: 암호화 처리
            is_logged_in=False,
        )
        if credentials_dict:
            account.credentials = credentials_dict

        db.add(account)
        db.commit()
        db.refresh(account)
        logger.info(f"서비스 계정 생성: profile_id={profile_id}, service_type={data.service_type}")
        return account

    def update(
        self,
        db: Session,
        account_id: int,
        data: ServiceAccountUpdate
    ) -> Optional[ServiceAccount]:
        """서비스 계정 수정"""
        account = self.get_by_id(db, account_id)
        if not account:
            return None

        update_data = data.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            if key == 'password' and value:
                # TODO: 암호화 처리
                account.password = value
            elif key == 'credentials' and value is not None:
                # credentials 병합 또는 덮어쓰기
                account.credentials = value
            else:
                setattr(account, key, value)

        account.updated_at = datetime.now()
        db.commit()
        db.refresh(account)
        logger.info(f"서비스 계정 수정: id={account_id}")
        return account

    def delete(self, db: Session, account_id: int) -> bool:
        """서비스 계정 삭제"""
        account = self.get_by_id(db, account_id)
        if not account:
            return False

        profile_id = account.profile_id
        service_type = account.service_type

        db.delete(account)
        db.commit()
        logger.info(f"서비스 계정 삭제: id={account_id}, profile_id={profile_id}, service_type={service_type}")
        return True

    def update_login_status(
        self,
        db: Session,
        account_id: int,
        is_logged_in: bool
    ) -> Optional[ServiceAccount]:
        """로그인 상태 업데이트"""
        account = self.get_by_id(db, account_id)
        if not account:
            return None

        account.is_logged_in = is_logged_in
        account.updated_at = datetime.now()
        db.commit()
        db.refresh(account)
        logger.info(f"서비스 계정 로그인 상태 업데이트: id={account_id} -> {is_logged_in}")
        return account

    def update_credentials(
        self,
        db: Session,
        account_id: int,
        credentials: Dict[str, Any]
    ) -> Optional[ServiceAccount]:
        """credentials 업데이트 (병합)"""
        account = self.get_by_id(db, account_id)
        if not account:
            return None

        current_creds = account.credentials or {}
        current_creds.update(credentials)
        account.credentials = current_creds
        account.updated_at = datetime.now()
        db.commit()
        db.refresh(account)
        return account

    def update_booking_info(
        self,
        db: Session,
        account_id: int,
        booking_info: Dict[str, Any]
    ) -> Optional[ServiceAccount]:
        """네이버 예약 정보 업데이트"""
        account = self.get_by_id(db, account_id)
        if not account:
            return None

        if account.service_type != "naver":
            raise ValueError(f"booking_info is only for naver accounts: service_type={account.service_type}")

        account.booking_info = booking_info
        account.updated_at = datetime.now()
        db.commit()
        db.refresh(account)
        return account


# 싱글톤 인스턴스
service_account_service = ServiceAccountService()

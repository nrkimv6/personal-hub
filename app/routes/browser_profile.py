"""
BrowserProfile 라우트 - 브라우저 프로필 관리 API
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.browser_profile import (
    BrowserProfile,
    BrowserProfileCreate,
    BrowserProfileUpdate,
    BrowserProfileWithAccounts,
)
from app.schemas.service_account import (
    ServiceAccountCreate,
    ServiceAccountResponse,
)
from app.shared.browser_profile import browser_profile_service
from app.shared.service_account import service_account_service

router = APIRouter(prefix="/api/v1/profiles", tags=["browser-profiles"])


# ============================================================
# 프로필 CRUD
# ============================================================

@router.get("/", response_model=List[BrowserProfileWithAccounts])
async def list_profiles(
    include_inactive: bool = Query(False, description="비활성 프로필 포함 여부"),
    db: Session = Depends(get_db)
):
    """브라우저 프로필 목록 조회 (서비스 계정 포함)"""
    profiles = browser_profile_service.get_all(db, include_inactive=include_inactive)
    return profiles


@router.get("/active", response_model=List[BrowserProfile])
async def list_active_profiles(db: Session = Depends(get_db)):
    """활성 프로필 목록 조회"""
    return browser_profile_service.get_active_profiles(db)


@router.post("/", response_model=BrowserProfile, status_code=201)
async def create_profile(
    data: BrowserProfileCreate,
    db: Session = Depends(get_db)
):
    """브라우저 프로필 생성"""
    # 중복 체크
    existing = browser_profile_service.get_by_profile_dir(db, data.profile_dir)
    if existing:
        raise HTTPException(status_code=400, detail=f"Profile directory already exists: {data.profile_dir}")

    existing_name = browser_profile_service.get_by_name(db, data.name)
    if existing_name:
        raise HTTPException(status_code=400, detail=f"Profile name already exists: {data.name}")

    return browser_profile_service.create(db, data)


@router.get("/{profile_id}", response_model=BrowserProfileWithAccounts)
async def get_profile(
    profile_id: int,
    db: Session = Depends(get_db)
):
    """프로필 상세 조회 (서비스 계정 포함)"""
    profile = browser_profile_service.get_by_id(db, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.put("/{profile_id}", response_model=BrowserProfile)
async def update_profile(
    profile_id: int,
    data: BrowserProfileUpdate,
    db: Session = Depends(get_db)
):
    """프로필 수정"""
    profile = browser_profile_service.update(db, profile_id, data)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.delete("/{profile_id}")
async def delete_profile(
    profile_id: int,
    remove_browser_data: bool = Query(False, description="브라우저 데이터 삭제 여부"),
    db: Session = Depends(get_db)
):
    """프로필 삭제 (cascade로 서비스 계정도 삭제됨)"""
    success = browser_profile_service.delete(db, profile_id, remove_browser_data=remove_browser_data)
    if not success:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"message": "Profile deleted successfully"}


@router.post("/{profile_id}/mark-used", response_model=BrowserProfile)
async def mark_profile_used(
    profile_id: int,
    db: Session = Depends(get_db)
):
    """프로필 사용 시간 업데이트"""
    profile = browser_profile_service.update_last_used(db, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


# ============================================================
# 프로필 내 서비스 계정 관리
# ============================================================

@router.get("/{profile_id}/accounts", response_model=List[ServiceAccountResponse])
async def list_profile_accounts(
    profile_id: int,
    db: Session = Depends(get_db)
):
    """프로필의 서비스 계정 목록 조회"""
    profile = browser_profile_service.get_by_id(db, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    return service_account_service.get_by_profile_id(db, profile_id)


@router.post("/{profile_id}/accounts", response_model=ServiceAccountResponse, status_code=201)
async def add_service_account(
    profile_id: int,
    data: ServiceAccountCreate,
    db: Session = Depends(get_db)
):
    """프로필에 서비스 계정 추가"""
    try:
        return service_account_service.create(db, profile_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

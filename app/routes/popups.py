"""
팝업 API 라우트 - 팝업스토어 관리

GET 엔드포인트는 공개, CUD 엔드포인트는 관리자 인증 필요
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.popup_service import popup_service
from app.schemas.popup import (
    PopupCreate,
    PopupUpdate,
    PopupResponse,
    PopupList,
    PopupImportFromInstagram,
)
from app.core.auth import require_admin, UserInfo

router = APIRouter(prefix="/api/v1/popups", tags=["popups"])


@router.get("", response_model=PopupList)
def get_popups(
    status: Optional[str] = Query(None, description="상태 (active/ended/cancelled)"),
    popup_status: Optional[str] = Query(None, description="진행 상태 (ongoing/upcoming/ended/ongoing_or_upcoming)"),
    source_type: Optional[str] = Query(None, description="출처 유형 (instagram/manual/web)"),
    is_bookmarked: Optional[bool] = Query(None, description="북마크 여부"),
    is_visited: Optional[bool] = Query(None, description="방문 완료 여부"),
    include_unknown_period: bool = Query(True, description="기간 미정 항목 포함 여부"),
    search: Optional[str] = Query(None, description="제목/장소/주소 검색"),
    sort_by: str = Query("end_date", description="정렬 기준 (end_date/start_date/created_at)"),
    sort_order: str = Query("asc", description="정렬 순서 (asc/desc)"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(50, ge=1, le=200, description="페이지 크기"),
    db: Session = Depends(get_db),
):
    """
    팝업 목록을 조회합니다.

    - 상태, 출처별 필터링 지원
    - 진행 상태(ongoing/upcoming/ended) 기반 필터링
    - 북마크, 방문 완료 필터링
    - 제목/장소/주소 검색 지원
    - 정렬 및 페이지네이션 지원
    """
    return popup_service.get_popups(
        db=db,
        status=status,
        popup_status=popup_status,
        source_type=source_type,
        is_bookmarked=is_bookmarked,
        is_visited=is_visited,
        include_unknown_period=include_unknown_period,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )


@router.get("/{popup_id}", response_model=PopupResponse)
def get_popup(popup_id: int, db: Session = Depends(get_db)):
    """
    팝업 상세 조회
    """
    popup = popup_service.get_popup(db, popup_id)
    if not popup:
        raise HTTPException(status_code=404, detail="Popup not found")
    return popup


@router.post("", response_model=PopupResponse, status_code=201)
def create_popup(
    data: PopupCreate,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    새 팝업을 생성합니다. (관리자 전용)
    """
    return popup_service.create_popup(db, data)


@router.put("/{popup_id}", response_model=PopupResponse)
def update_popup(
    popup_id: int,
    data: PopupUpdate,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    팝업을 수정합니다. (관리자 전용)
    """
    popup = popup_service.update_popup(db, popup_id, data)
    if not popup:
        raise HTTPException(status_code=404, detail="Popup not found")
    return popup


@router.delete("/{popup_id}", status_code=204)
def delete_popup(
    popup_id: int,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    팝업을 삭제합니다. (관리자 전용)
    """
    success = popup_service.delete_popup(db, popup_id)
    if not success:
        raise HTTPException(status_code=404, detail="Popup not found")
    return None


@router.post("/{popup_id}/bookmark", response_model=PopupResponse)
def toggle_bookmark(
    popup_id: int,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    팝업 북마크를 토글합니다. (관리자 전용)
    """
    popup = popup_service.toggle_bookmark(db, popup_id)
    if not popup:
        raise HTTPException(status_code=404, detail="Popup not found")
    return popup


@router.post("/{popup_id}/visited", response_model=PopupResponse)
def toggle_visited(
    popup_id: int,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    팝업 방문 완료 상태를 토글합니다. (관리자 전용)
    """
    popup = popup_service.toggle_visited(db, popup_id)
    if not popup:
        raise HTTPException(status_code=404, detail="Popup not found")
    return popup


@router.post("/import-from-instagram", response_model=PopupResponse, status_code=201)
def import_from_instagram(
    data: PopupImportFromInstagram,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    Instagram 게시물에서 팝업을 생성합니다. (관리자 전용)

    - LLM 분류 결과를 기반으로 팝업 자동 생성
    - 이미 연결된 팝업이 있으면 해당 팝업 반환
    """
    popup = popup_service.import_from_instagram(db, data)
    if not popup:
        raise HTTPException(status_code=404, detail="Instagram post not found")
    return popup


@router.get("/{popup_id}/instagram-source")
def get_instagram_source(popup_id: int, db: Session = Depends(get_db)):
    """
    팝업의 Instagram 출처 정보를 조회합니다. (lazy loading용)
    """
    return popup_service.get_instagram_source(db, popup_id)

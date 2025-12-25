"""
이벤트 API 라우트 - 독립 이벤트 관리

GET 엔드포인트는 공개, CUD 엔드포인트는 관리자 인증 필요
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.event_service import event_service
from app.schemas.event import (
    EventCreate,
    EventUpdate,
    EventResponse,
    EventList,
    EventImportFromInstagram,
    EventImportFromUrl,
    EventImportFromUrlResponse,
)
from app.core.auth import require_admin, UserInfo

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.get("", response_model=EventList)
def get_events(
    event_type: Optional[str] = Query(None, description="이벤트 유형 (event/popup/ambassador/other)"),
    status: Optional[str] = Query(None, description="상태 (active/ended/cancelled)"),
    event_status: Optional[str] = Query(None, description="진행 상태 (ongoing/upcoming/ended/ongoing_or_upcoming)"),
    source_type: Optional[str] = Query(None, description="출처 유형 (instagram/manual/web/other)"),
    url_type: Optional[str] = Query(None, description="URL 유형 (google_form/naver_form/shop/survey/other)"),
    is_bookmarked: Optional[bool] = Query(None, description="북마크 여부"),
    is_participated: Optional[bool] = Query(None, description="참여 완료 여부"),
    include_unknown_period: bool = Query(True, description="기간 미정 항목 포함 여부"),
    search: Optional[str] = Query(None, description="제목/요약/주최자 검색"),
    sort_by: str = Query("event_end", description="정렬 기준 (event_end/event_start/created_at)"),
    sort_order: str = Query("asc", description="정렬 순서 (asc/desc)"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(50, ge=1, le=200, description="페이지 크기"),
    db: Session = Depends(get_db),
):
    """
    이벤트 목록을 조회합니다.

    - 이벤트 유형, 상태, 출처별 필터링 지원
    - 진행 상태(ongoing/upcoming/ended) 기반 필터링
    - 북마크, 참여 완료 필터링
    - 제목/요약/주최자 검색 지원
    - 정렬 및 페이지네이션 지원
    """
    return event_service.get_events(
        db=db,
        event_type=event_type,
        status=status,
        event_status=event_status,
        source_type=source_type,
        url_type=url_type,
        is_bookmarked=is_bookmarked,
        is_participated=is_participated,
        include_unknown_period=include_unknown_period,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )


@router.get("/{event_id}", response_model=EventResponse)
def get_event(event_id: int, db: Session = Depends(get_db)):
    """
    이벤트 상세 조회
    """
    event = event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("", response_model=EventResponse, status_code=201)
def create_event(
    data: EventCreate,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    새 이벤트를 생성합니다. (관리자 전용)
    """
    # URL 중복 체크 (경고만)
    if data.event_url:
        existing = event_service.check_duplicate_url(db, data.event_url)
        if existing:
            # 중복이 있어도 생성은 허용, 응답에 경고 포함하지 않음 (클라이언트에서 처리)
            pass

    return event_service.create_event(db, data)


@router.put("/{event_id}", response_model=EventResponse)
def update_event(
    event_id: int,
    data: EventUpdate,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    이벤트를 수정합니다. (관리자 전용)
    """
    event = event_service.update_event(db, event_id, data)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.delete("/{event_id}", status_code=204)
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    이벤트를 삭제합니다. (관리자 전용)
    """
    success = event_service.delete_event(db, event_id)
    if not success:
        raise HTTPException(status_code=404, detail="Event not found")
    return None


@router.post("/{event_id}/bookmark", response_model=EventResponse)
def toggle_bookmark(
    event_id: int,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    이벤트 북마크를 토글합니다. (관리자 전용)
    """
    event = event_service.toggle_bookmark(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("/{event_id}/participate", response_model=EventResponse)
def toggle_participate(
    event_id: int,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    이벤트 참여 완료 상태를 토글합니다. (관리자 전용)
    """
    event = event_service.toggle_participated(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("/import-from-instagram", response_model=EventResponse, status_code=201)
def import_from_instagram(
    data: EventImportFromInstagram,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    Instagram 게시물에서 이벤트를 생성합니다. (관리자 전용)

    - LLM 분류 결과(llm_tag, llm_urls, llm_event_* 등)를 기반으로 이벤트 자동 생성
    - 이미 연결된 이벤트가 있으면 해당 이벤트 반환
    """
    event = event_service.import_from_instagram(db, data)
    if not event:
        raise HTTPException(status_code=404, detail="Instagram post not found")
    return event


@router.post("/import-from-url", response_model=EventImportFromUrlResponse)
def import_from_url(
    data: EventImportFromUrl,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    URL에서 이벤트 정보를 추출합니다. (관리자 전용)

    - Playwright로 페이지 로드
    - 페이지 유형별 최적화된 추출기 사용 (Google Forms, Naver Form, Naver Blog 등)
    - LLM으로 이벤트 정보 분석
    - auto_save=True면 Event 자동 생성

    지원 페이지 유형:
    - google_forms: Google Forms 설문
    - naver_form: Naver Form 설문
    - naver_blog_pc: Naver Blog PC 버전
    - naver_blog_mobile: Naver Blog 모바일 버전
    - generic: 기타 일반 웹페이지 (시맨틱 태그/OG 메타데이터 기반)
    """
    return event_service.import_from_url(db, data)


@router.get("/check-duplicate-url", response_model=Optional[EventResponse])
def check_duplicate_url(
    url: str = Query(..., description="확인할 URL"),
    exclude_id: Optional[int] = Query(None, description="제외할 이벤트 ID"),
    db: Session = Depends(get_db),
):
    """
    동일 URL로 등록된 이벤트가 있는지 확인합니다.
    """
    existing = event_service.check_duplicate_url(db, url, exclude_id)
    if not existing:
        return None
    return event_service._to_response(db, existing)


@router.get("/{event_id}/instagram-source")
def get_instagram_source(event_id: int, db: Session = Depends(get_db)):
    """
    이벤트의 Instagram 출처 정보를 조회합니다. (lazy loading용)
    """
    return event_service.get_instagram_source(db, event_id)

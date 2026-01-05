"""
브라우저 확장 프로그램용 API 엔드포인트
"""
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.instagram_post import InstagramPost
from app.modules.instagram.services.classifier_service import ClassifierService

router = APIRouter(prefix="/api/v1/instagram/extension", tags=["instagram-extension"])


class ExtensionPostImage(BaseModel):
    """이미지 데이터"""
    src: str
    alt: Optional[str] = ""


class ExtensionPostCreate(BaseModel):
    """브라우저 확장에서 전송하는 게시물 데이터"""
    post_id: str
    account: Optional[str] = None
    url: str
    caption: Optional[str] = None
    images: Optional[List[ExtensionPostImage]] = None
    posted_at: Optional[str] = None
    display_time: Optional[str] = None
    post_type: str = "NORMAL"
    is_reel: bool = False
    collected_at: Optional[str] = None


class ExtensionPostResponse(BaseModel):
    """응답"""
    success: bool
    message: str
    post_id: Optional[int] = None
    is_duplicate: bool = False


class ExtensionBatchRequest(BaseModel):
    """배치 요청"""
    posts: List[ExtensionPostCreate]


class ExtensionBatchResponse(BaseModel):
    """배치 응답"""
    success: bool
    total: int
    saved: int
    duplicates: int


class ExtensionScheduleResponse(BaseModel):
    """스케줄 응답"""
    action: Optional[str] = None  # "START" | "STOP" | None


@router.get("/status")
async def get_extension_status():
    """확장 프로그램 연결 상태 확인용"""
    return {
        "status": "ok",
        "server": "monitor-page",
        "timestamp": datetime.now().isoformat()
    }


@router.post("/posts", response_model=ExtensionPostResponse)
async def create_post_from_extension(
    data: ExtensionPostCreate,
    db: Session = Depends(get_db)
):
    """
    브라우저 확장에서 수집한 게시물 저장
    """
    # 중복 체크
    existing = db.query(InstagramPost).filter(
        InstagramPost.post_id == data.post_id
    ).first()

    if existing:
        return ExtensionPostResponse(
            success=True,
            message="이미 존재하는 게시물",
            post_id=existing.id,
            is_duplicate=True
        )

    # 이미지 데이터 변환
    images_data = None
    if data.images:
        images_data = [{"src": img.src, "alt": img.alt} for img in data.images]

    # 게시물 생성
    post = InstagramPost(
        post_id=data.post_id,
        account=data.account,
        url=data.url,
        caption=data.caption,
        images=images_data,
        posted_at=_parse_datetime(data.posted_at),
        display_time=data.display_time,
        post_type=data.post_type,
        is_reel=data.is_reel,
        is_ad=data.post_type == "SPONSORED",
        collected_at=datetime.now(),
        source="extension"
    )

    db.add(post)
    db.commit()
    db.refresh(post)

    # 자동 분류
    try:
        classifier = ClassifierService(db)
        classifier.classify_post(post)
    except Exception as e:
        print(f"[Extension] Classification error: {e}")

    return ExtensionPostResponse(
        success=True,
        message="저장 완료",
        post_id=post.id,
        is_duplicate=False
    )


@router.post("/posts/batch", response_model=ExtensionBatchResponse)
async def create_posts_batch(
    data: ExtensionBatchRequest,
    db: Session = Depends(get_db)
):
    """
    여러 게시물 일괄 저장
    """
    saved_count = 0
    duplicate_count = 0

    for post_data in data.posts:
        # 중복 체크
        existing = db.query(InstagramPost).filter(
            InstagramPost.post_id == post_data.post_id
        ).first()

        if existing:
            duplicate_count += 1
            continue

        # 이미지 데이터 변환
        images_data = None
        if post_data.images:
            images_data = [{"src": img.src, "alt": img.alt} for img in post_data.images]

        # 게시물 생성
        post = InstagramPost(
            post_id=post_data.post_id,
            account=post_data.account,
            url=post_data.url,
            caption=post_data.caption,
            images=images_data,
            posted_at=_parse_datetime(post_data.posted_at),
            display_time=post_data.display_time,
            post_type=post_data.post_type,
            is_reel=post_data.is_reel,
            is_ad=post_data.post_type == "SPONSORED",
            collected_at=datetime.now(),
            source="extension"
        )

        db.add(post)
        saved_count += 1

    db.commit()

    # 저장된 게시물들 자동 분류
    if saved_count > 0:
        try:
            classifier = ClassifierService(db)
            # 최근 저장된 extension 게시물 분류
            recent_posts = db.query(InstagramPost).filter(
                InstagramPost.source == "extension",
                InstagramPost.classified_at == None
            ).limit(saved_count).all()

            for post in recent_posts:
                classifier.classify_post(post)
        except Exception as e:
            print(f"[Extension] Batch classification error: {e}")

    return ExtensionBatchResponse(
        success=True,
        total=len(data.posts),
        saved=saved_count,
        duplicates=duplicate_count
    )


@router.get("/schedule", response_model=ExtensionScheduleResponse)
async def get_schedule(db: Session = Depends(get_db)):
    """
    스케줄 확인 (폴링)

    TODO: 실제 스케줄 로직 구현
    - DB에서 extension 크롤링 스케줄 확인
    - 시작/중지 시간 체크
    """
    # 현재는 항상 null 반환 (수동 제어)
    # 추후 스케줄 테이블 연동 시 구현
    return ExtensionScheduleResponse(action=None)


def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """ISO 형식 문자열을 datetime으로 변환"""
    if not dt_str:
        return None
    try:
        # Z를 +00:00으로 변환
        if dt_str.endswith('Z'):
            dt_str = dt_str[:-1] + '+00:00'
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None

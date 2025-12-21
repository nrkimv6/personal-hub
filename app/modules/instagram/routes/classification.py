"""Instagram Classification API Routes - 태그 및 분류 관련 API."""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from ..models.schemas import (
    TagSchema,
    TagCreateSchema,
    TagUpdateSchema,
    KeywordSchema,
    KeywordCreateSchema,
    KeywordBulkCreateSchema,
    ClassifyRequestSchema,
    ClassifyResultSchema,
)
from ..services import ClassifierService, TagService

logger = logging.getLogger("instagram.classification_api")

router = APIRouter(prefix="/api/v1/instagram", tags=["instagram-classification"])


# ============== 태그 관리 ==============


@router.get("/tags", response_model=List[TagSchema])
async def get_tags(
    include_inactive: bool = Query(False, description="비활성 태그 포함 여부"),
    db: Session = Depends(get_db),
):
    """태그 목록 조회."""
    service = TagService(db)
    tags = service.get_tags(include_inactive)

    return [
        TagSchema(
            id=t.id,
            name=t.name,
            display_name=t.display_name,
            description=t.description,
            color=t.color,
            is_active=t.is_active,
            keyword_count=len(t.keywords) if t.keywords else 0,
        )
        for t in tags
    ]


@router.get("/tags/{tag_id}", response_model=TagSchema)
async def get_tag(
    tag_id: int,
    db: Session = Depends(get_db),
):
    """태그 상세 조회."""
    service = TagService(db)
    tag = service.get_tag_by_id(tag_id)

    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    return TagSchema(
        id=tag.id,
        name=tag.name,
        display_name=tag.display_name,
        description=tag.description,
        color=tag.color,
        is_active=tag.is_active,
        keyword_count=len(tag.keywords) if tag.keywords else 0,
    )


@router.post("/tags", response_model=TagSchema)
async def create_tag(
    data: TagCreateSchema,
    db: Session = Depends(get_db),
):
    """태그 생성."""
    service = TagService(db)

    # 중복 확인
    if service.get_tag_by_name(data.name):
        raise HTTPException(status_code=400, detail="Tag already exists")

    tag = service.create_tag(
        name=data.name,
        display_name=data.display_name,
        description=data.description,
        color=data.color,
    )

    return TagSchema(
        id=tag.id,
        name=tag.name,
        display_name=tag.display_name,
        description=tag.description,
        color=tag.color,
        is_active=tag.is_active,
        keyword_count=0,
    )


@router.put("/tags/{tag_id}", response_model=TagSchema)
async def update_tag(
    tag_id: int,
    data: TagUpdateSchema,
    db: Session = Depends(get_db),
):
    """태그 수정."""
    service = TagService(db)

    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    tag = service.update_tag(tag_id, **update_data)

    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    return TagSchema(
        id=tag.id,
        name=tag.name,
        display_name=tag.display_name,
        description=tag.description,
        color=tag.color,
        is_active=tag.is_active,
        keyword_count=len(tag.keywords) if tag.keywords else 0,
    )


@router.delete("/tags/{tag_id}")
async def delete_tag(
    tag_id: int,
    db: Session = Depends(get_db),
):
    """태그 삭제."""
    service = TagService(db)

    if not service.delete_tag(tag_id):
        raise HTTPException(status_code=404, detail="Tag not found")

    return {"success": True, "message": "Tag deleted successfully"}


# ============== 키워드 관리 ==============


@router.get("/tags/{tag_id}/keywords", response_model=List[KeywordSchema])
async def get_keywords(
    tag_id: int,
    include_inactive: bool = Query(False, description="비활성 키워드 포함 여부"),
    db: Session = Depends(get_db),
):
    """태그의 키워드 목록 조회."""
    service = TagService(db)

    # 태그 존재 확인
    if not service.get_tag_by_id(tag_id):
        raise HTTPException(status_code=404, detail="Tag not found")

    keywords = service.get_keywords_by_tag(tag_id, include_inactive)

    return [
        KeywordSchema(
            id=k.id,
            keyword=k.keyword,
            is_regex=k.is_regex,
            is_case_sensitive=k.is_case_sensitive,
            is_active=k.is_active,
        )
        for k in keywords
    ]


@router.post("/tags/{tag_id}/keywords", response_model=KeywordSchema)
async def add_keyword(
    tag_id: int,
    data: KeywordCreateSchema,
    db: Session = Depends(get_db),
):
    """키워드 추가."""
    service = TagService(db)

    kw = service.add_keyword(
        tag_id=tag_id,
        keyword=data.keyword,
        is_regex=data.is_regex,
        is_case_sensitive=data.is_case_sensitive,
    )

    if not kw:
        raise HTTPException(status_code=404, detail="Tag not found")

    return KeywordSchema(
        id=kw.id,
        keyword=kw.keyword,
        is_regex=kw.is_regex,
        is_case_sensitive=kw.is_case_sensitive,
        is_active=kw.is_active,
    )


@router.post("/tags/{tag_id}/keywords/bulk")
async def add_keywords_bulk(
    tag_id: int,
    data: KeywordBulkCreateSchema,
    db: Session = Depends(get_db),
):
    """키워드 일괄 추가."""
    service = TagService(db)

    # 태그 존재 확인
    if not service.get_tag_by_id(tag_id):
        raise HTTPException(status_code=404, detail="Tag not found")

    added = service.add_keywords_bulk(tag_id, data.keywords)

    return {"success": True, "added": added}


@router.delete("/keywords/{keyword_id}")
async def delete_keyword(
    keyword_id: int,
    db: Session = Depends(get_db),
):
    """키워드 삭제."""
    service = TagService(db)

    if not service.delete_keyword(keyword_id):
        raise HTTPException(status_code=404, detail="Keyword not found")

    return {"success": True, "message": "Keyword deleted successfully"}


@router.patch("/keywords/{keyword_id}/toggle")
async def toggle_keyword(
    keyword_id: int,
    db: Session = Depends(get_db),
):
    """키워드 활성화/비활성화 토글."""
    service = TagService(db)

    kw = service.toggle_keyword(keyword_id)

    if not kw:
        raise HTTPException(status_code=404, detail="Keyword not found")

    return {"success": True, "is_active": kw.is_active}


# ============== 분류 ==============


@router.post("/classify", response_model=ClassifyResultSchema)
async def classify_posts(
    data: ClassifyRequestSchema,
    db: Session = Depends(get_db),
):
    """선택한 게시물 분류."""
    service = ClassifierService(db)
    result = service.classify_posts_batch(data.post_ids)

    return ClassifyResultSchema(
        total=result["total"],
        classified=result["classified"],
        details=result["details"],
    )


@router.post("/classify/all", response_model=ClassifyResultSchema)
async def reclassify_all(
    db: Session = Depends(get_db),
):
    """전체 게시물 재분류.

    기존 분류 결과를 삭제하고 전체 게시물을 재분류합니다.
    """
    service = ClassifierService(db)
    result = service.reclassify_all()

    logger.info(f"Reclassified all posts: {result['classified']}/{result['total']}")

    return ClassifyResultSchema(
        total=result["total"],
        classified=result["classified"],
        details=result["details"],
    )


@router.get("/posts/{post_id}/tags")
async def get_post_tags(
    post_id: int,
    db: Session = Depends(get_db),
):
    """게시물의 태그 목록 조회."""
    service = ClassifierService(db)
    tags = service.get_post_tags(post_id)

    return {"post_id": post_id, "tags": tags}

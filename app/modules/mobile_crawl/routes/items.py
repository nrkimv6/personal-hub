"""
모바일 크롤링 아이템 조회 API

수집된 아이템을 조회합니다.
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import json
import logging

from app.database import get_db
from ..services.item_service import MobileCrawlItemService

logger = logging.getLogger(__name__)

router = APIRouter()


# ============= 스키마 =============

class ItemResponse(BaseModel):
    """아이템 응답"""
    id: int
    target_id: int
    run_id: Optional[int]
    title: str
    item_url: Optional[str]
    image_url: Optional[str]
    attributes: str  # JSON 문자열
    is_changed: bool
    first_seen_at: str
    last_seen_at: str
    created_at: str

    class Config:
        from_attributes = True


# ============= API 엔드포인트 =============

@router.get("/targets/{target_id}/items", response_model=List[ItemResponse])
def get_items_by_target(
    target_id: int,
    run_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    대상별 아이템 조회

    특정 크롤링 대상에서 수집된 아이템 목록을 조회합니다.
    """
    items = MobileCrawlItemService.get_items_by_target(
        db=db,
        target_id=target_id,
        run_id=run_id,
        skip=skip,
        limit=limit
    )

    return [
        ItemResponse(
            id=item.id,
            target_id=item.target_id,
            run_id=item.run_id,
            title=item.title,
            item_url=item.item_url,
            image_url=item.image_url,
            attributes=item.attributes or "{}",
            is_changed=item.is_changed,
            first_seen_at=item.first_seen_at.isoformat(),
            last_seen_at=item.last_seen_at.isoformat(),
            created_at=item.created_at.isoformat()
        )
        for item in items
    ]


@router.get("/items/{item_id}", response_model=ItemResponse)
def get_item(item_id: int, db: Session = Depends(get_db)):
    """
    아이템 상세 조회

    특정 아이템의 상세 정보를 조회합니다.
    """
    item = MobileCrawlItemService.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="아이템을 찾을 수 없습니다")

    return ItemResponse(
        id=item.id,
        target_id=item.target_id,
        run_id=item.run_id,
        title=item.title,
        item_url=item.item_url,
        image_url=item.image_url,
        attributes=item.attributes or "{}",
        is_changed=item.is_changed,
        first_seen_at=item.first_seen_at.isoformat(),
        last_seen_at=item.last_seen_at.isoformat(),
        created_at=item.created_at.isoformat()
    )


@router.get("/runs/{run_id}/items", response_model=List[ItemResponse])
def get_items_by_run(
    run_id: int,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    실행별 아이템 조회

    특정 실행에서 수집된 아이템 목록을 조회합니다.
    """
    items = MobileCrawlItemService.get_items_by_run(
        db=db,
        run_id=run_id,
        skip=skip,
        limit=limit
    )

    return [
        ItemResponse(
            id=item.id,
            target_id=item.target_id,
            run_id=item.run_id,
            title=item.title,
            item_url=item.item_url,
            image_url=item.image_url,
            attributes=item.attributes or "{}",
            is_changed=item.is_changed,
            first_seen_at=item.first_seen_at.isoformat(),
            last_seen_at=item.last_seen_at.isoformat(),
            created_at=item.created_at.isoformat()
        )
        for item in items
    ]


@router.get("/items/changed", response_model=List[ItemResponse])
def get_changed_items(
    target_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    변경된 아이템 조회

    속성이 변경된 아이템 목록을 조회합니다.
    """
    items = MobileCrawlItemService.get_changed_items(
        db=db,
        target_id=target_id,
        skip=skip,
        limit=limit
    )

    return [
        ItemResponse(
            id=item.id,
            target_id=item.target_id,
            run_id=item.run_id,
            title=item.title,
            item_url=item.item_url,
            image_url=item.image_url,
            attributes=item.attributes or "{}",
            is_changed=item.is_changed,
            first_seen_at=item.first_seen_at.isoformat(),
            last_seen_at=item.last_seen_at.isoformat(),
            created_at=item.created_at.isoformat()
        )
        for item in items
    ]

"""
모바일 크롤링 아이템 서비스

수집된 아이템의 저장, 조회, 변경 감지 로직을 담당합니다.
"""
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, func
from typing import List, Optional, Dict, Any
from datetime import datetime
import json
import logging

from app.models.mobile_crawl import MobileCrawlItem

logger = logging.getLogger(__name__)


class MobileCrawlItemService:
    """모바일 크롤링 아이템 서비스"""

    @staticmethod
    def save_items(
        db: Session,
        target_id: int,
        run_id: Optional[int],
        items: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """
        아이템 목록 저장 및 변경 감지

        Args:
            db: 데이터베이스 세션
            target_id: 크롤링 대상 ID
            run_id: 실행 ID (TaskScheduleRun)
            items: 아이템 목록 [{title, item_url, image_url, attributes, raw_html}, ...]

        Returns:
            {
                "new": int,      # 신규 아이템 수
                "updated": int,  # 변경된 아이템 수
                "unchanged": int # 변경 없는 아이템 수
            }
        """
        stats = {"new": 0, "updated": 0, "unchanged": 0}

        for item_data in items:
            item_url = item_data.get("item_url")

            # 기존 아이템 조회 (item_url 기준)
            existing = None
            if item_url:
                existing = db.query(MobileCrawlItem).filter(
                    and_(
                        MobileCrawlItem.target_id == target_id,
                        MobileCrawlItem.item_url == item_url
                    )
                ).first()

            if existing:
                # 속성 변경 감지
                new_attributes = json.dumps(item_data.get("attributes", {}), ensure_ascii=False)
                is_changed = existing.attributes != new_attributes

                # 업데이트
                existing.title = item_data.get("title", existing.title)
                existing.image_url = item_data.get("image_url", existing.image_url)
                existing.attributes = new_attributes
                existing.raw_html = item_data.get("raw_html", existing.raw_html)
                existing.last_seen_at = datetime.utcnow()
                existing.is_changed = is_changed
                existing.run_id = run_id

                if is_changed:
                    stats["updated"] += 1
                    logger.info(f"아이템 변경 감지: {existing.id} - {existing.title}")
                else:
                    stats["unchanged"] += 1

            else:
                # 신규 아이템 생성
                new_item = MobileCrawlItem(
                    target_id=target_id,
                    run_id=run_id,
                    title=item_data.get("title", ""),
                    item_url=item_url,
                    image_url=item_data.get("image_url"),
                    attributes=json.dumps(item_data.get("attributes", {}), ensure_ascii=False),
                    raw_html=item_data.get("raw_html"),
                    is_changed=False
                )
                db.add(new_item)
                stats["new"] += 1
                logger.info(f"신규 아이템 추가: {item_data.get('title')}")

        db.commit()
        return stats

    @staticmethod
    def get_items_by_target(
        db: Session,
        target_id: int,
        run_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 50
    ) -> List[MobileCrawlItem]:
        """
        대상별 아이템 조회

        Args:
            db: 데이터베이스 세션
            target_id: 크롤링 대상 ID
            run_id: 실행 ID 필터 (None=전체)
            skip: 건너뛸 개수
            limit: 최대 개수

        Returns:
            아이템 목록
        """
        query = db.query(MobileCrawlItem).filter(
            MobileCrawlItem.target_id == target_id
        )

        if run_id is not None:
            query = query.filter(MobileCrawlItem.run_id == run_id)

        return query.order_by(desc(MobileCrawlItem.last_seen_at)).offset(skip).limit(limit).all()

    @staticmethod
    def get_items_by_run(
        db: Session,
        run_id: int,
        skip: int = 0,
        limit: int = 50
    ) -> List[MobileCrawlItem]:
        """
        실행별 아이템 조회

        Args:
            db: 데이터베이스 세션
            run_id: 실행 ID
            skip: 건너뛸 개수
            limit: 최대 개수

        Returns:
            아이템 목록
        """
        return db.query(MobileCrawlItem).filter(
            MobileCrawlItem.run_id == run_id
        ).order_by(desc(MobileCrawlItem.created_at)).offset(skip).limit(limit).all()

    @staticmethod
    def get_item(db: Session, item_id: int) -> Optional[MobileCrawlItem]:
        """아이템 상세 조회"""
        return db.query(MobileCrawlItem).filter(
            MobileCrawlItem.id == item_id
        ).first()

    @staticmethod
    def get_changed_items(
        db: Session,
        target_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 50
    ) -> List[MobileCrawlItem]:
        """
        변경된 아이템 조회

        Args:
            db: 데이터베이스 세션
            target_id: 크롤링 대상 ID (None=전체)
            skip: 건너뛸 개수
            limit: 최대 개수

        Returns:
            변경된 아이템 목록
        """
        query = db.query(MobileCrawlItem).filter(
            MobileCrawlItem.is_changed == True
        )

        if target_id is not None:
            query = query.filter(MobileCrawlItem.target_id == target_id)

        return query.order_by(desc(MobileCrawlItem.last_seen_at)).offset(skip).limit(limit).all()

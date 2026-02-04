"""
모바일 크롤링 대상 서비스

크롤링 대상의 생성, 조회, 수정, 삭제 비즈니스 로직을 담당합니다.
"""
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from typing import List, Optional, Dict, Any
from datetime import datetime
import json
import logging

from app.models.mobile_crawl import MobileCrawlTarget, MobileCrawlItem

logger = logging.getLogger(__name__)


class MobileCrawlTargetService:
    """모바일 크롤링 대상 서비스"""

    @staticmethod
    def create_target(
        db: Session,
        name: str,
        url: str,
        crawl_type: str = "list",
        parse_config: Dict[str, Any] = None,
        is_active: bool = True
    ) -> MobileCrawlTarget:
        """
        크롤링 대상 생성

        Args:
            db: 데이터베이스 세션
            name: 대상 이름
            url: 대상 URL
            crawl_type: 크롤링 타입 (list, detail)
            parse_config: 파싱 설정 (딕셔너리)
            is_active: 활성화 여부

        Returns:
            생성된 크롤링 대상

        Raises:
            ValueError: URL이 이미 존재하는 경우
        """
        # 중복 URL 확인
        existing = db.query(MobileCrawlTarget).filter(
            MobileCrawlTarget.url == url
        ).first()

        if existing:
            raise ValueError(f"URL이 이미 등록되어 있습니다: {url}")

        # 파싱 설정 JSON 변환
        parse_config_json = json.dumps(parse_config or {}, ensure_ascii=False)

        target = MobileCrawlTarget(
            name=name,
            url=url,
            crawl_type=crawl_type,
            parse_config=parse_config_json,
            is_active=is_active
        )

        db.add(target)
        db.commit()
        db.refresh(target)

        logger.info(f"크롤링 대상 생성: {target.id} - {target.name}")
        return target

    @staticmethod
    def get_target(db: Session, target_id: int) -> Optional[MobileCrawlTarget]:
        """크롤링 대상 조회"""
        return db.query(MobileCrawlTarget).filter(
            MobileCrawlTarget.id == target_id
        ).first()

    @staticmethod
    def get_targets(
        db: Session,
        is_active: Optional[bool] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[MobileCrawlTarget]:
        """
        크롤링 대상 목록 조회

        Args:
            db: 데이터베이스 세션
            is_active: 활성화 필터 (None=전체, True=활성, False=비활성)
            skip: 건너뛸 개수
            limit: 최대 개수

        Returns:
            크롤링 대상 목록
        """
        query = db.query(MobileCrawlTarget)

        if is_active is not None:
            query = query.filter(MobileCrawlTarget.is_active == is_active)

        return query.order_by(desc(MobileCrawlTarget.created_at)).offset(skip).limit(limit).all()

    @staticmethod
    def update_target(
        db: Session,
        target_id: int,
        name: Optional[str] = None,
        url: Optional[str] = None,
        crawl_type: Optional[str] = None,
        parse_config: Optional[Dict[str, Any]] = None,
        is_active: Optional[bool] = None
    ) -> Optional[MobileCrawlTarget]:
        """
        크롤링 대상 수정

        Args:
            db: 데이터베이스 세션
            target_id: 대상 ID
            name: 새 이름
            url: 새 URL
            crawl_type: 새 크롤링 타입
            parse_config: 새 파싱 설정
            is_active: 새 활성화 상태

        Returns:
            수정된 크롤링 대상
        """
        target = MobileCrawlTargetService.get_target(db, target_id)
        if not target:
            return None

        if name is not None:
            target.name = name

        if url is not None:
            # 다른 대상의 URL과 중복 확인
            existing = db.query(MobileCrawlTarget).filter(
                MobileCrawlTarget.url == url,
                MobileCrawlTarget.id != target_id
            ).first()
            if existing:
                raise ValueError(f"URL이 이미 다른 대상에 등록되어 있습니다: {url}")
            target.url = url

        if crawl_type is not None:
            target.crawl_type = crawl_type

        if parse_config is not None:
            target.parse_config = json.dumps(parse_config, ensure_ascii=False)

        if is_active is not None:
            target.is_active = is_active

        target.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(target)

        logger.info(f"크롤링 대상 수정: {target.id} - {target.name}")
        return target

    @staticmethod
    def delete_target(db: Session, target_id: int) -> bool:
        """
        크롤링 대상 삭제

        Args:
            db: 데이터베이스 세션
            target_id: 대상 ID

        Returns:
            삭제 성공 여부
        """
        target = MobileCrawlTargetService.get_target(db, target_id)
        if not target:
            return False

        logger.info(f"크롤링 대상 삭제: {target.id} - {target.name}")
        db.delete(target)
        db.commit()
        return True

    @staticmethod
    def get_target_stats(db: Session, target_id: int) -> Dict[str, Any]:
        """
        크롤링 대상 통계

        Args:
            db: 데이터베이스 세션
            target_id: 대상 ID

        Returns:
            {
                "total_items": int,
                "latest_run_id": int,
                "latest_run_at": str,
                "new_items_count": int,
                "changed_items_count": int
            }
        """
        target = MobileCrawlTargetService.get_target(db, target_id)
        if not target:
            return {}

        # 전체 아이템 수
        total_items = db.query(func.count(MobileCrawlItem.id)).filter(
            MobileCrawlItem.target_id == target_id
        ).scalar() or 0

        # 최근 실행 정보
        latest_item = db.query(MobileCrawlItem).filter(
            MobileCrawlItem.target_id == target_id,
            MobileCrawlItem.run_id.isnot(None)
        ).order_by(desc(MobileCrawlItem.created_at)).first()

        latest_run_id = latest_item.run_id if latest_item else None
        latest_run_at = latest_item.created_at.isoformat() if latest_item else None

        # 최근 24시간 내 신규/변경 아이템
        new_items = db.query(func.count(MobileCrawlItem.id)).filter(
            MobileCrawlItem.target_id == target_id,
            MobileCrawlItem.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0)
        ).scalar() or 0

        changed_items = db.query(func.count(MobileCrawlItem.id)).filter(
            MobileCrawlItem.target_id == target_id,
            MobileCrawlItem.is_changed == True
        ).scalar() or 0

        return {
            "total_items": total_items,
            "latest_run_id": latest_run_id,
            "latest_run_at": latest_run_at,
            "new_items_count": new_items,
            "changed_items_count": changed_items
        }

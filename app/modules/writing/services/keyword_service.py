"""
키워드 통계 관리 서비스.

키워드 승격, 불용어 관리 등.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import KeywordStats, WritingElement, WritingStopword

logger = logging.getLogger(__name__)


class KeywordService:
    """키워드 관리 서비스."""

    def __init__(self, db: Session):
        self.db = db

    def get_keywords(
        self,
        limit: int = 100,
        offset: int = 0,
        min_frequency: int = 0,
        include_stopwords: bool = False,
        include_promoted: bool = True,
    ) -> list[KeywordStats]:
        """키워드 목록 조회."""
        query = self.db.query(KeywordStats)

        if not include_stopwords:
            query = query.filter(KeywordStats.is_stopword == 0)
        if not include_promoted:
            query = query.filter(KeywordStats.is_promoted == 0)
        if min_frequency > 0:
            query = query.filter(KeywordStats.frequency >= min_frequency)

        return query.order_by(desc(KeywordStats.frequency)).offset(offset).limit(limit).all()

    def count_keywords(
        self,
        min_frequency: int = 0,
        include_stopwords: bool = False,
        include_promoted: bool = True,
    ) -> int:
        """키워드 총 개수 조회 (필터 조건 적용)."""
        query = self.db.query(KeywordStats)

        if not include_stopwords:
            query = query.filter(KeywordStats.is_stopword == 0)
        if not include_promoted:
            query = query.filter(KeywordStats.is_promoted == 0)
        if min_frequency > 0:
            query = query.filter(KeywordStats.frequency >= min_frequency)

        return query.count()

    def get_candidates(self, limit: int = 50, min_frequency: int = 100) -> list[KeywordStats]:
        """승격 후보 키워드 조회 (미검토 + 미승격 + 고빈도)."""
        return (
            self.db.query(KeywordStats)
            .filter(
                KeywordStats.is_stopword == 0,
                KeywordStats.is_promoted == 0,
                KeywordStats.reviewed_at.is_(None),
                KeywordStats.frequency >= min_frequency,
            )
            .order_by(desc(KeywordStats.frequency))
            .limit(limit)
            .all()
        )

    def promote_to_element(
        self,
        keyword_id: int,
        season_hint: Optional[str] = None,
    ) -> WritingElement:
        """키워드를 writing_elements로 승격."""
        kw = self.db.query(KeywordStats).get(keyword_id)
        if not kw:
            raise ValueError(f"Keyword not found: {keyword_id}")

        if kw.is_promoted:
            raise ValueError(f"Already promoted: {kw.keyword}")

        if kw.is_stopword:
            raise ValueError(f"Cannot promote stopword: {kw.keyword}")

        # 이미 동일한 이름의 element가 존재하는지 확인
        existing_element = (
            self.db.query(WritingElement)
            .filter_by(category=WritingElement.CATEGORY_KEYWORD, name=kw.keyword)
            .first()
        )

        if existing_element:
            # 기존 element에 연결하고 frequency 업데이트
            existing_element.frequency = max(existing_element.frequency or 0, kw.frequency)
            existing_element.source_keyword_id = kw.id
            if season_hint:
                existing_element.season_hint = season_hint
            element = existing_element
            logger.info(f"Linked keyword to existing element: {kw.keyword} → element_id={element.id}")
        else:
            # writing_elements에 새로 추가
            element = WritingElement(
                category=WritingElement.CATEGORY_KEYWORD,
                name=kw.keyword,
                frequency=kw.frequency,
                source_keyword_id=kw.id,
                season_hint=season_hint,
                is_active=1,
            )
            self.db.add(element)
            self.db.flush()
            logger.info(f"Promoted keyword: {kw.keyword} → element_id={element.id}")

        # keyword_stats 업데이트
        kw.is_promoted = 1
        kw.element_id = element.id
        kw.reviewed_at = datetime.now()

        self.db.commit()

        return element

    def demote_keyword(self, keyword_id: int) -> KeywordStats:
        """승격된 키워드를 원래 상태로 되돌림 (writing_elements에서도 삭제)."""
        kw = self.db.query(KeywordStats).get(keyword_id)
        if not kw:
            raise ValueError(f"Keyword not found: {keyword_id}")

        if not kw.is_promoted:
            raise ValueError(f"Not promoted: {kw.keyword}")

        # writing_elements에서 해당 element 삭제 (있으면)
        if kw.element_id:
            element = self.db.query(WritingElement).get(kw.element_id)
            if element:
                self.db.delete(element)
                logger.info(f"Deleted element: {element.name} (id={element.id})")

        # keyword_stats 업데이트
        kw.is_promoted = 0
        kw.element_id = None
        kw.reviewed_at = None  # 검토 상태도 리셋

        self.db.commit()
        logger.info(f"Demoted keyword: {kw.keyword}")

        return kw

    def promote_batch(
        self,
        limit: int = 50,
        min_frequency: int = 100,
        season_hint: Optional[str] = None,
    ) -> list[WritingElement]:
        """상위 N개 키워드 일괄 승격."""
        candidates = self.get_candidates(limit=limit, min_frequency=min_frequency)
        promoted = []

        for kw in candidates:
            try:
                element = self.promote_to_element(kw.id, season_hint)
                promoted.append(element)
            except ValueError as e:
                logger.warning(f"Skip promotion: {e}")

        logger.info(f"Batch promoted: {len(promoted)} keywords")
        return promoted

    def mark_as_stopword(self, keyword_id: int) -> KeywordStats:
        """키워드를 불용어로 마킹."""
        kw = self.db.query(KeywordStats).get(keyword_id)
        if not kw:
            raise ValueError(f"Keyword not found: {keyword_id}")

        kw.is_stopword = 1
        kw.is_promoted = 0
        kw.reviewed_at = datetime.now()

        # writing_stopwords에도 추가
        existing = self.db.query(WritingStopword).filter_by(word=kw.keyword).first()
        if not existing:
            stopword = WritingStopword(
                word=kw.keyword,
                category=WritingStopword.CATEGORY_REVIEWED,
            )
            self.db.add(stopword)

        self.db.commit()
        logger.info(f"Marked as stopword: {kw.keyword}")

        return kw

    def get_stopwords(self) -> list[WritingStopword]:
        """불용어 목록 조회."""
        return self.db.query(WritingStopword).order_by(WritingStopword.word).all()

    def add_stopword(self, word: str, category: str = "general") -> WritingStopword:
        """불용어 추가."""
        existing = self.db.query(WritingStopword).filter_by(word=word).first()
        if existing:
            raise ValueError(f"Already exists: {word}")

        stopword = WritingStopword(word=word, category=category)
        self.db.add(stopword)

        # keyword_stats에도 반영
        kw = self.db.query(KeywordStats).filter_by(keyword=word).first()
        if kw:
            kw.is_stopword = 1
            kw.reviewed_at = datetime.now()

        self.db.commit()
        return stopword

    def remove_stopword(self, stopword_id: int) -> bool:
        """불용어 삭제."""
        stopword = self.db.query(WritingStopword).get(stopword_id)
        if not stopword:
            return False

        # keyword_stats에서도 플래그 해제
        kw = self.db.query(KeywordStats).filter_by(keyword=stopword.word).first()
        if kw:
            kw.is_stopword = 0

        self.db.delete(stopword)
        self.db.commit()
        return True

    def get_stats(self) -> dict:
        """키워드 통계 요약."""
        total = self.db.query(KeywordStats).count()
        promoted = self.db.query(KeywordStats).filter_by(is_promoted=1).count()
        stopwords = self.db.query(KeywordStats).filter_by(is_stopword=1).count()
        reviewed = self.db.query(KeywordStats).filter(KeywordStats.reviewed_at.isnot(None)).count()

        return {
            "total_keywords": total,
            "promoted": promoted,
            "stopwords": stopwords,
            "reviewed": reviewed,
            "pending_review": total - reviewed,
        }

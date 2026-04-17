"""Element Selector - 글쓰기 요소 선택기 (쿨다운 적용)."""

import random
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.writing import WritingSource
from app.models.writing_element import WritingElement, WritingElementUsage


logger = logging.getLogger(__name__)


# 쿨다운 설정 (일 단위)
COOLDOWN_DAYS = {
    "source": 7,  # Mix용 소스 쿨다운
    "topic": 5,  # 소재 쿨다운
    "keyword": 3,  # 키워드 쿨다운 (여러 개 사용하므로 짧게)
    "tone": 3,
    "style": 3,
    "format": 3,
    "emotion": 3,
}


class ElementSelector:
    """요소 선택기 - 쿨다운 및 시즌 가중치 적용.

    기능:
    - 최근 N일 내 사용된 요소/소스 제외
    - 시즌 기반 가중치 적용
    - Fallback 전략 (쿨다운 완화)
    - 당일 슬롯 간 중복 방지
    """

    def __init__(self, db: Session):
        """ElementSelector 초기화.

        Args:
            db: SQLAlchemy 세션
        """
        self.db = db

    # =========================================================================
    # 소스 선택 (Mix Writing용)
    # =========================================================================

    def get_available_sources(
        self,
        cooldown_days: Optional[int] = None,
        exclude_ids: Optional[list[int]] = None,
    ) -> list[WritingSource]:
        """쿨다운이 적용된 사용 가능한 소스 목록.

        Args:
            cooldown_days: 쿨다운 일수 (None이면 기본값 사용)
            exclude_ids: 추가로 제외할 소스 ID 목록 (당일 슬롯용)

        Returns:
            사용 가능한 WritingSource 목록
        """
        if cooldown_days is None:
            cooldown_days = COOLDOWN_DAYS["source"]

        cutoff = datetime.now() - timedelta(days=cooldown_days)

        # 최근 사용된 source_id 조회
        recent_query = (
            self.db.query(WritingElementUsage.source_id)
            .filter(
                WritingElementUsage.source_id.isnot(None),
                WritingElementUsage.used_at > cutoff,
            )
            .distinct()
        )
        recent_ids = [r[0] for r in recent_query.all()]

        # 당일 제외 목록 합치기
        if exclude_ids:
            recent_ids = list(set(recent_ids + exclude_ids))

        # 제외하고 조회
        query = self.db.query(WritingSource)
        if recent_ids:
            query = query.filter(WritingSource.id.notin_(recent_ids))

        return query.all()

    def select_sources(
        self,
        count: int = 3,
        exclude_ids: Optional[list[int]] = None,
    ) -> list[WritingSource]:
        """쿨다운이 적용된 소스 선택 (Fallback 포함).

        Args:
            count: 선택할 소스 개수
            exclude_ids: 제외할 소스 ID 목록

        Returns:
            선택된 WritingSource 목록
        """
        cooldown = COOLDOWN_DAYS["source"]

        # 1차: 정상 쿨다운
        available = self.get_available_sources(cooldown, exclude_ids)
        if len(available) >= count:
            return random.sample(available, count)

        logger.warning(f"소스 부족 (쿨다운 {cooldown}일): {len(available)}개, 쿨다운 완화")

        # 2차: 쿨다운 절반
        available = self.get_available_sources(cooldown // 2, exclude_ids)
        if len(available) >= count:
            return random.sample(available, count)

        logger.warning(f"소스 부족 (쿨다운 {cooldown // 2}일): {len(available)}개, 전체에서 선택")

        # 3차: 쿨다운 없이 (exclude만 적용)
        available = self.get_available_sources(0, exclude_ids)
        if len(available) >= count:
            return random.sample(available, count)

        # 4차: 전체에서 랜덤 (최후의 수단)
        all_sources = self.db.query(WritingSource).all()
        if len(all_sources) >= count:
            return random.sample(all_sources, count)

        return all_sources  # 부족해도 있는 것만 반환

    # =========================================================================
    # 요소 선택 (Random Writing용)
    # =========================================================================

    def get_available_elements(
        self,
        category: str,
        cooldown_days: Optional[int] = None,
        exclude_ids: Optional[list[int]] = None,
    ) -> list[WritingElement]:
        """쿨다운이 적용된 사용 가능한 요소 목록.

        Args:
            category: 요소 카테고리 (topic, keyword, tone 등)
            cooldown_days: 쿨다운 일수 (None이면 기본값 사용)
            exclude_ids: 추가로 제외할 요소 ID 목록

        Returns:
            사용 가능한 WritingElement 목록
        """
        if cooldown_days is None:
            cooldown_days = COOLDOWN_DAYS.get(category, 3)

        cutoff = datetime.now() - timedelta(days=cooldown_days)

        # 최근 사용된 element_id 조회
        recent_query = (
            self.db.query(WritingElementUsage.element_id)
            .join(WritingElement)
            .filter(
                WritingElementUsage.element_id.isnot(None),
                WritingElement.category == category,
                WritingElementUsage.used_at > cutoff,
            )
            .distinct()
        )
        recent_ids = [r[0] for r in recent_query.all()]

        # 당일 제외 목록 합치기
        if exclude_ids:
            recent_ids = list(set(recent_ids + exclude_ids))

        # 제외하고 조회
        query = self.db.query(WritingElement).filter(
            WritingElement.category == category,
            WritingElement.is_active.is_(True),
        )
        if recent_ids:
            query = query.filter(WritingElement.id.notin_(recent_ids))

        return query.all()

    def select_element(
        self,
        category: str,
        exclude_ids: Optional[list[int]] = None,
        season: Optional[str] = None,
    ) -> Optional[WritingElement]:
        """단일 요소 선택 (Fallback 및 시즌 가중치 적용).

        Args:
            category: 요소 카테고리
            exclude_ids: 제외할 요소 ID 목록
            season: 현재 시즌 (가중치 적용용)

        Returns:
            선택된 WritingElement (없으면 None)
        """
        result = self.select_elements(category, 1, exclude_ids, season)
        return result[0] if result else None

    def select_elements(
        self,
        category: str,
        count: int = 1,
        exclude_ids: Optional[list[int]] = None,
        season: Optional[str] = None,
    ) -> list[WritingElement]:
        """복수 요소 선택 (Fallback 및 시즌 가중치 적용).

        Args:
            category: 요소 카테고리
            count: 선택할 개수
            exclude_ids: 제외할 요소 ID 목록
            season: 현재 시즌 (가중치 적용용)

        Returns:
            선택된 WritingElement 목록
        """
        cooldown = COOLDOWN_DAYS.get(category, 3)

        # 1차: 정상 쿨다운
        available = self.get_available_elements(category, cooldown, exclude_ids)
        if len(available) >= count:
            return self._weighted_sample(available, count, season)

        logger.warning(
            f"요소 부족 ({category}, 쿨다운 {cooldown}일): {len(available)}개, 쿨다운 완화"
        )

        # 2차: 쿨다운 절반
        available = self.get_available_elements(category, cooldown // 2, exclude_ids)
        if len(available) >= count:
            return self._weighted_sample(available, count, season)

        logger.warning(
            f"요소 부족 ({category}, 쿨다운 {cooldown // 2}일): {len(available)}개, 전체에서 선택"
        )

        # 3차: 쿨다운 없이 (exclude만 적용)
        available = self.get_available_elements(category, 0, exclude_ids)
        if len(available) >= count:
            return self._weighted_sample(available, count, season)

        # 4차: 전체에서 (최후의 수단)
        all_elements = (
            self.db.query(WritingElement)
            .filter(
                WritingElement.category == category,
                WritingElement.is_active.is_(True),
            )
            .all()
        )
        if len(all_elements) >= count:
            return self._weighted_sample(all_elements, count, season)

        return all_elements  # 부족해도 있는 것만 반환

    def _weighted_sample(
        self,
        elements: list[WritingElement],
        count: int,
        season: Optional[str] = None,
    ) -> list[WritingElement]:
        """시즌 가중치가 적용된 샘플링.

        Args:
            elements: 후보 요소 목록
            count: 선택할 개수
            season: 현재 시즌

        Returns:
            선택된 요소 목록
        """
        if not elements:
            return []

        if not season:
            # 시즌 없으면 균등 확률
            return random.sample(elements, min(count, len(elements)))

        # 시즌 매칭 요소에 가중치 부여
        weights = []
        for elem in elements:
            if elem.matches_season(season):
                weights.append(3.0)  # 시즌 매칭 시 3배 가중치
            else:
                weights.append(1.0)

        # 가중치 기반 선택 (중복 없이)
        selected = []
        remaining = list(zip(elements, weights))

        for _ in range(min(count, len(elements))):
            if not remaining:
                break

            elems, wgts = zip(*remaining)
            chosen = random.choices(elems, weights=wgts, k=1)[0]
            selected.append(chosen)

            # 선택된 것 제거
            remaining = [(e, w) for e, w in remaining if e.id != chosen.id]

        return selected

    # =========================================================================
    # 사용 이력 기록
    # =========================================================================

    def record_source_usage(
        self,
        source_ids: list[int],
        generated_writing_id: int,
    ) -> None:
        """소스 사용 이력 기록.

        Args:
            source_ids: 사용된 소스 ID 목록
            generated_writing_id: 생성된 글 ID
        """
        for source_id in source_ids:
            usage = WritingElementUsage(
                source_id=source_id,
                generated_writing_id=generated_writing_id,
            )
            self.db.add(usage)

    def record_element_usage(
        self,
        elements: list[WritingElement],
        generated_writing_id: int,
    ) -> None:
        """요소 사용 이력 기록.

        Args:
            elements: 사용된 요소 목록
            generated_writing_id: 생성된 글 ID
        """
        for element in elements:
            usage = WritingElementUsage(
                element_id=element.id,
                generated_writing_id=generated_writing_id,
            )
            self.db.add(usage)

    # =========================================================================
    # 통계/디버그
    # =========================================================================

    def get_usage_stats(self, category: Optional[str] = None) -> dict:
        """요소별 사용 통계 조회.

        Args:
            category: 특정 카테고리만 조회 (None이면 전체)

        Returns:
            {element_id: {"name": str, "count": int, "last_used": datetime}}
        """
        query = (
            self.db.query(
                WritingElement.id,
                WritingElement.category,
                WritingElement.name,
                func.count(WritingElementUsage.id).label("usage_count"),
                func.max(WritingElementUsage.used_at).label("last_used"),
            )
            .outerjoin(WritingElementUsage)
            .group_by(WritingElement.id)
        )

        if category:
            query = query.filter(WritingElement.category == category)

        result = {}
        for row in query.all():
            result[row.id] = {
                "category": row.category,
                "name": row.name,
                "count": row.usage_count or 0,
                "last_used": row.last_used,
            }

        return result

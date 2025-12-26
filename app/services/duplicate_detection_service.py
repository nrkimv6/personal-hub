"""
중복 감지 서비스 - 이벤트/팝업 중복 검출 및 병합

이벤트와 팝업의 중복 여부를 판단하고, 병합할 수 있도록 지원
"""
import json
import logging
from typing import List, Optional, Tuple, Dict, Any, Literal
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models.event import Event
from app.models.popup import Popup
from app.models.entity_source import EntitySource
from app.utils.similarity import (
    normalize,
    normalize_url,
    dates_overlap,
    jaccard_similarity,
    text_similarity,
    compare_address,
    extract_korean_brand,
)

logger = logging.getLogger(__name__)

# 중복 판단 임계값
EVENT_DUPLICATE_THRESHOLD = 0.7
POPUP_DUPLICATE_THRESHOLD = 0.7

# 불확실 영역 (수동 확인 필요)
UNCERTAIN_THRESHOLD_LOW = 0.5


class DuplicateDetectionService:
    """중복 감지 서비스"""

    def calculate_event_similarity(self, e1: Event, e2: Event) -> float:
        """두 이벤트의 유사도 계산 (0.0 ~ 1.0)

        Args:
            e1: 첫 번째 이벤트
            e2: 두 번째 이벤트

        Returns:
            유사도 점수 (0.0 ~ 1.0)
        """
        # 참여 URL이 같으면 무조건 동일 이벤트
        if e1.event_url and e2.event_url:
            if normalize_url(e1.event_url) == normalize_url(e2.event_url):
                return 1.0

        score = 0.0

        # 1. 기간 중복 (가중치: 0.25)
        if dates_overlap(e1.event_start, e1.event_end, e2.event_start, e2.event_end):
            score += 0.25

        # 2. 주최사/계정 일치 (가중치: 0.25)
        if e1.organizer and e2.organizer:
            if normalize(e1.organizer) == normalize(e2.organizer):
                score += 0.25
        elif e1.source_instagram_account and e2.source_instagram_account:
            if e1.source_instagram_account == e2.source_instagram_account:
                score += 0.20

        # 3. 경품 유사도 (가중치: 0.25)
        prizes1 = self._parse_prizes(e1.prizes)
        prizes2 = self._parse_prizes(e2.prizes)
        if prizes1 and prizes2:
            prize_sim = jaccard_similarity(prizes1, prizes2)
            score += 0.25 * prize_sim

        # 4. 제목 유사도 (가중치: 0.25)
        if e1.title and e2.title:
            title_sim = text_similarity(e1.title, e2.title)
            score += 0.25 * title_sim

        return score

    def calculate_popup_similarity(self, p1: Popup, p2: Popup) -> float:
        """두 팝업의 유사도 계산 (0.0 ~ 1.0)

        Args:
            p1: 첫 번째 팝업
            p2: 두 번째 팝업

        Returns:
            유사도 점수 (0.0 ~ 1.0)
        """
        score = 0.0

        # 1. 브랜드명 일치 (가중치: 0.35)
        if p1.brand and p2.brand:
            brand1 = extract_korean_brand(p1.brand)
            brand2 = extract_korean_brand(p2.brand)
            if brand1 and brand2 and brand1 == brand2:
                score += 0.35

        # 2. 기간 중복 (가중치: 0.25)
        if dates_overlap(p1.start_date, p1.end_date, p2.start_date, p2.end_date):
            score += 0.25

        # 3. 장소명 일치 (가중치: 0.25) - 주소보다 일관성 높음
        if p1.venue_name and p2.venue_name:
            if normalize(p1.venue_name) == normalize(p2.venue_name):
                score += 0.25
        elif p1.address and p2.address:
            # 장소명이 없으면 주소 비교
            addr_sim = compare_address(p1.address, p2.address)
            score += 0.20 * addr_sim

        # 4. 제목 유사도 (가중치: 0.15)
        if p1.title and p2.title:
            title_sim = text_similarity(p1.title, p2.title)
            score += 0.15 * title_sim

        return score

    def find_duplicate_event(
        self,
        db: Session,
        event_data: Dict[str, Any],
        exclude_id: Optional[int] = None,
    ) -> Optional[Tuple[Event, float]]:
        """새 이벤트 데이터와 중복되는 기존 이벤트 찾기

        Args:
            db: DB 세션
            event_data: 새 이벤트 데이터 (dict)
            exclude_id: 제외할 이벤트 ID (수정 시)

        Returns:
            (중복 이벤트, 유사도) 또는 None
        """
        # URL 기반 빠른 검색
        event_url = event_data.get("event_url")
        if event_url:
            normalized = normalize_url(event_url)
            existing = db.query(Event).filter(
                Event.event_url.isnot(None)
            ).all()

            for event in existing:
                if exclude_id and event.id == exclude_id:
                    continue
                if normalize_url(event.event_url) == normalized:
                    return (event, 1.0)

        # 임시 Event 객체 생성하여 유사도 계산
        temp_event = Event(
            title=event_data.get("title"),
            event_url=event_data.get("event_url"),
            event_start=event_data.get("event_start"),
            event_end=event_data.get("event_end"),
            organizer=event_data.get("organizer"),
            prizes=json.dumps(event_data.get("prizes", [])),
            source_instagram_account=event_data.get("source_instagram_account"),
        )

        # 후보 조회 (기간이 겹치거나, 같은 주최자)
        candidates = self._get_event_candidates(db, event_data, exclude_id)

        best_match = None
        best_score = 0.0

        for candidate in candidates:
            similarity = self.calculate_event_similarity(temp_event, candidate)
            if similarity >= EVENT_DUPLICATE_THRESHOLD and similarity > best_score:
                best_match = candidate
                best_score = similarity

        if best_match:
            return (best_match, best_score)
        return None

    def find_duplicate_popup(
        self,
        db: Session,
        popup_data: Dict[str, Any],
        exclude_id: Optional[int] = None,
    ) -> Optional[Tuple[Popup, float]]:
        """새 팝업 데이터와 중복되는 기존 팝업 찾기

        Args:
            db: DB 세션
            popup_data: 새 팝업 데이터 (dict)
            exclude_id: 제외할 팝업 ID (수정 시)

        Returns:
            (중복 팝업, 유사도) 또는 None
        """
        # 임시 Popup 객체 생성
        temp_popup = Popup(
            title=popup_data.get("title"),
            brand=popup_data.get("brand"),
            start_date=popup_data.get("start_date"),
            end_date=popup_data.get("end_date"),
            venue_name=popup_data.get("venue_name"),
            address=popup_data.get("address"),
        )

        # 후보 조회
        candidates = self._get_popup_candidates(db, popup_data, exclude_id)

        best_match = None
        best_score = 0.0

        for candidate in candidates:
            similarity = self.calculate_popup_similarity(temp_popup, candidate)
            if similarity >= POPUP_DUPLICATE_THRESHOLD and similarity > best_score:
                best_match = candidate
                best_score = similarity

        if best_match:
            return (best_match, best_score)
        return None

    def find_similar_events(
        self,
        db: Session,
        event: Event,
        threshold: float = UNCERTAIN_THRESHOLD_LOW,
    ) -> List[Tuple[Event, float]]:
        """특정 이벤트와 유사한 이벤트들 찾기

        Args:
            db: DB 세션
            event: 기준 이벤트
            threshold: 최소 유사도 임계값

        Returns:
            [(유사 이벤트, 유사도)] 리스트
        """
        event_data = {
            "title": event.title,
            "event_url": event.event_url,
            "event_start": event.event_start,
            "event_end": event.event_end,
            "organizer": event.organizer,
            "source_instagram_account": event.source_instagram_account,
        }
        candidates = self._get_event_candidates(db, event_data, event.id)

        similar = []
        for candidate in candidates:
            similarity = self.calculate_event_similarity(event, candidate)
            if similarity >= threshold:
                similar.append((candidate, similarity))

        # 유사도 내림차순 정렬
        similar.sort(key=lambda x: x[1], reverse=True)
        return similar

    def find_similar_popups(
        self,
        db: Session,
        popup: Popup,
        threshold: float = UNCERTAIN_THRESHOLD_LOW,
    ) -> List[Tuple[Popup, float]]:
        """특정 팝업과 유사한 팝업들 찾기

        Args:
            db: DB 세션
            popup: 기준 팝업
            threshold: 최소 유사도 임계값

        Returns:
            [(유사 팝업, 유사도)] 리스트
        """
        popup_data = {
            "brand": popup.brand,
            "start_date": popup.start_date,
            "end_date": popup.end_date,
            "venue_name": popup.venue_name,
        }
        candidates = self._get_popup_candidates(db, popup_data, popup.id)

        similar = []
        for candidate in candidates:
            similarity = self.calculate_popup_similarity(popup, candidate)
            if similarity >= threshold:
                similar.append((candidate, similarity))

        similar.sort(key=lambda x: x[1], reverse=True)
        return similar

    def _get_event_candidates(
        self,
        db: Session,
        event_data: Dict[str, Any],
        exclude_id: Optional[int] = None,
    ) -> List[Event]:
        """이벤트 중복 후보 조회

        기간이 겹치거나, 같은 주최자/계정인 이벤트들
        """
        query = db.query(Event)

        if exclude_id:
            query = query.filter(Event.id != exclude_id)

        conditions = []

        # 기간 조건
        start = event_data.get("event_start")
        end = event_data.get("event_end")
        if start and end:
            # 기간이 겹치는 이벤트
            conditions.append(
                and_(
                    Event.event_start <= end,
                    Event.event_end >= start,
                )
            )

        # 주최자 조건
        organizer = event_data.get("organizer")
        if organizer:
            conditions.append(Event.organizer == organizer)

        # Instagram 계정 조건
        account = event_data.get("source_instagram_account")
        if account:
            conditions.append(Event.source_instagram_account == account)

        if conditions:
            query = query.filter(or_(*conditions))

        # 최대 100개까지 검색
        return query.limit(100).all()

    def _get_popup_candidates(
        self,
        db: Session,
        popup_data: Dict[str, Any],
        exclude_id: Optional[int] = None,
    ) -> List[Popup]:
        """팝업 중복 후보 조회

        같은 브랜드이거나, 기간이 겹치는 팝업들
        """
        query = db.query(Popup)

        if exclude_id:
            query = query.filter(Popup.id != exclude_id)

        conditions = []

        # 브랜드 조건
        brand = popup_data.get("brand")
        if brand:
            conditions.append(Popup.brand == brand)

        # 기간 조건
        start = popup_data.get("start_date")
        end = popup_data.get("end_date")
        if start and end:
            conditions.append(
                and_(
                    Popup.start_date <= end,
                    Popup.end_date >= start,
                )
            )

        # 장소명 조건
        venue = popup_data.get("venue_name")
        if venue:
            conditions.append(Popup.venue_name == venue)

        if conditions:
            query = query.filter(or_(*conditions))

        return query.limit(100).all()

    def _parse_prizes(self, prizes: Any) -> List[str]:
        """prizes 필드 파싱 (JSON 문자열 또는 리스트)"""
        if not prizes:
            return []
        if isinstance(prizes, list):
            return prizes
        if isinstance(prizes, str):
            try:
                return json.loads(prizes)
            except json.JSONDecodeError:
                return [prizes]
        return []

    def merge_event_data(
        self,
        existing: Event,
        new_data: Dict[str, Any],
        source_priority: int = 50,
    ) -> Dict[str, Any]:
        """새 데이터를 기존 이벤트에 병합

        우선순위가 높은 출처의 데이터가 빈 필드를 채움

        Args:
            existing: 기존 이벤트
            new_data: 새 데이터
            source_priority: 새 출처의 우선순위

        Returns:
            병합된 필드 목록 {"field": "new_value"}
        """
        merged = {}

        # 우선순위 기반 필드 업데이트 (빈 값만 채움)
        update_fields = [
            "title", "organizer", "event_url", "event_start", "event_end",
            "summary", "prizes", "winner_count", "thumbnail_url",
        ]

        for field in update_fields:
            existing_value = getattr(existing, field, None)
            new_value = new_data.get(field)

            # 기존 값이 없고 새 값이 있으면 업데이트
            if not existing_value and new_value:
                merged[field] = new_value
            # 또는 새 출처 우선순위가 더 높고 새 값이 있으면 업데이트
            # (이 로직은 향후 확장 가능)

        return merged

    def merge_popup_data(
        self,
        existing: Popup,
        new_data: Dict[str, Any],
        source_priority: int = 50,
    ) -> Dict[str, Any]:
        """새 데이터를 기존 팝업에 병합"""
        merged = {}

        update_fields = [
            "title", "brand", "start_date", "end_date",
            "venue_name", "address", "operating_hours",
            "description", "thumbnail_url",
        ]

        for field in update_fields:
            existing_value = getattr(existing, field, None)
            new_value = new_data.get(field)

            if not existing_value and new_value:
                merged[field] = new_value

        return merged


# 싱글톤 인스턴스
duplicate_detection_service = DuplicateDetectionService()

"""Popup SQLAlchemy Model - 팝업스토어 관리."""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, Date
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import Base


class Popup(Base):
    """팝업스토어 모델 - Event와 분리된 팝업 관리."""
    __tablename__ = "popups"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 기본 정보
    title = Column(Text, nullable=False)
    thumbnail_url = Column(Text)  # Instagram 첫 번째 이미지

    # 기간
    start_date = Column(Date, index=True)
    end_date = Column(Date, index=True)

    # 위치 (팝업 핵심 정보)
    venue_name = Column(String)  # 장소명 (예: 더현대 서울)
    address = Column(Text)  # 주소
    floor_info = Column(String)  # 층 정보 (예: B2F)

    # 운영 정보
    operating_hours = Column(String)  # 운영 시간 (예: 10:30-20:00)
    admission_fee = Column(String)  # 입장료 (무료/유료/금액)
    reservation_required = Column(Boolean, default=False)  # 사전예약 필요
    reservation_url = Column(Text)  # 예약 URL

    # 브랜드/주최
    brand = Column(String)  # 브랜드명
    organizer = Column(String)  # 주최사
    collaboration = Column(String)  # 콜라보 정보

    # 상세
    summary = Column(Text)  # 요약
    highlights = Column(JSON, default=list)  # 주요 볼거리
    official_url = Column(Text)  # 공식 페이지
    additional_urls = Column(JSON, default=list)  # 추가 URL들

    # 출처
    source_type = Column(String, nullable=False, default="instagram", index=True)  # instagram/manual/web
    source_instagram_post_id = Column(Integer, ForeignKey("instagram_posts.id", ondelete="SET NULL"), index=True)
    source_instagram_url = Column(Text)
    source_instagram_account = Column(String)

    # 사용자 관리
    is_bookmarked = Column(Boolean, default=False, index=True)
    is_visited = Column(Boolean, default=False)  # 방문 완료
    user_note = Column(Text)

    # 입력 출처 (AI/사람/AI수정)
    input_source = Column(String, default="human", index=True)  # 'ai', 'human', 'ai_edited'

    # 다중 출처 통합 (entity_sources 테이블과 연계)
    source_count = Column(Integer, default=1)  # 연결된 출처 수
    primary_source_id = Column(Integer)  # entity_sources.id (대표 출처)
    confidence_score = Column(Integer, default=50)  # 정보 신뢰도 (0-100)
    merged_from = Column(Text)  # JSON: 병합된 팝업 ID 목록

    # 상태
    status = Column(String, default="active", index=True)  # active/ended/cancelled

    # 메타데이터
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 관계
    source_instagram_post = relationship("InstagramPost", foreign_keys=[source_instagram_post_id])

    def __repr__(self):
        return f"<Popup(id={self.id}, title={self.title[:20] if self.title else 'N/A'}, venue={self.venue_name})>"

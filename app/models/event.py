"""Event SQLAlchemy Model - 독립 이벤트 관리."""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, Date
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import Base


class Event(Base):
    """독립 이벤트 모델 - Instagram과 분리된 이벤트 관리."""
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 기본 정보
    title = Column(Text, nullable=False)
    event_type = Column(String, nullable=False, default="event", index=True)  # event/popup/ambassador/other
    status = Column(String, default="active", index=True)  # active/ended/cancelled

    # 참여 URL (핵심)
    event_url = Column(Text)  # 메인 참여 URL
    url_type = Column(String)  # google_form/naver_form/shop/survey/other
    additional_urls = Column(JSON, default=list)  # 추가 URL 목록

    # 기간
    event_start = Column(Date)
    event_end = Column(Date, index=True)
    announcement_date = Column(Date)  # 당첨자 발표일

    # 이벤트 상세
    organizer = Column(String)  # 주최사/브랜드
    summary = Column(Text)  # 이벤트 요약
    prizes = Column(JSON, default=list)  # ["경품1", "경품2"]
    winner_count = Column(Integer)
    purchase_required = Column(String)  # yes_all/yes_partial/no

    # 팝업 전용 (event_type='popup')
    location_venue = Column(String)  # 장소명
    location_address = Column(Text)  # 주소

    # 출처 정보
    source_type = Column(String, nullable=False, default="manual", index=True)  # instagram/manual/web/other
    source_instagram_post_id = Column(Integer, ForeignKey("instagram_posts.id", ondelete="SET NULL"), index=True)
    source_url = Column(Text)  # 기타 출처 URL
    source_note = Column(Text)  # 출처 메모

    # 사용자 관리
    is_bookmarked = Column(Boolean, default=False, index=True)
    is_participated = Column(Boolean, default=False)
    user_note = Column(Text)

    # 메타데이터
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 관계
    source_instagram_post = relationship("InstagramPost", foreign_keys=[source_instagram_post_id])

    def __repr__(self):
        return f"<Event(id={self.id}, title={self.title[:20] if self.title else 'N/A'}, type={self.event_type})>"

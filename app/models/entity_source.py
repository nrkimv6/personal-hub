"""EntitySource SQLAlchemy Model - 이벤트/팝업의 다중 출처 관리."""

from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import Base


class EntitySource(Base):
    """엔티티 출처 모델 - Event/Popup의 다중 출처를 통합 관리.

    다형성(polymorphic) 관계로 event 또는 popup에 연결됨.
    하나의 이벤트/팝업이 여러 출처(Instagram, 웹 크롤링 등)를 가질 수 있음.
    """
    __tablename__ = "entity_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 엔티티 참조 (다형성)
    entity_type = Column(String, nullable=False, index=True)  # 'event' | 'popup'
    entity_id = Column(Integer, nullable=False)  # events.id 또는 popups.id

    # 출처 유형 및 참조
    source_type = Column(String, nullable=False, index=True)  # 'instagram' | 'web' | 'manual'
    source_id = Column(Integer)  # instagram_posts.id 또는 crawled_pages.id
    source_url = Column(Text)  # 원본 URL
    source_account = Column(String)  # 계정명/사이트명

    # 출처 메타정보
    priority = Column(Integer, default=50)  # 우선순위 (1-100, 높을수록 신뢰도 높음)
    is_primary = Column(Integer, default=0, index=True)  # 대표 출처 여부
    contributed_fields = Column(Text)  # JSON: 이 출처에서 가져온 필드 목록

    # 추출 정보 (LLM 분석 결과 원본)
    extracted_data = Column(Text)  # JSON: 이 출처에서 추출한 원본 데이터

    # 메타데이터
    discovered_at = Column(DateTime, default=datetime.now)
    created_at = Column(DateTime, default=datetime.now)

    # 복합 인덱스
    __table_args__ = (
        Index('idx_entity_sources_entity', 'entity_type', 'entity_id'),
        Index('idx_entity_sources_source', 'source_type', 'source_id'),
    )

    def __repr__(self):
        return f"<EntitySource(id={self.id}, type={self.entity_type}, entity_id={self.entity_id}, source={self.source_type})>"

    @property
    def is_instagram(self) -> bool:
        """Instagram 출처인지 확인."""
        return self.source_type == "instagram"

    @property
    def is_web(self) -> bool:
        """웹 크롤링 출처인지 확인."""
        return self.source_type == "web"

    @property
    def is_manual(self) -> bool:
        """수동 입력 출처인지 확인."""
        return self.source_type == "manual"

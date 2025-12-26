"""
EntitySource 서비스 - 이벤트/팝업 다중 출처 관리
"""
import json
import logging
from typing import List, Optional, Literal

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.entity_source import EntitySource
from app.models.event import Event
from app.models.popup import Popup
from app.schemas.entity_source import (
    EntitySourceCreate,
    EntitySourceUpdate,
    EntitySourceResponse,
    EntitySourceList,
)

logger = logging.getLogger(__name__)


class EntitySourceService:
    """엔티티 출처 서비스"""

    def get_sources(
        self,
        db: Session,
        entity_type: Literal["event", "popup"],
        entity_id: int,
    ) -> EntitySourceList:
        """엔티티의 출처 목록 조회"""
        sources = (
            db.query(EntitySource)
            .filter(
                and_(
                    EntitySource.entity_type == entity_type,
                    EntitySource.entity_id == entity_id,
                )
            )
            .order_by(EntitySource.is_primary.desc(), EntitySource.priority.desc())
            .all()
        )

        items = [self._to_response(source) for source in sources]

        return EntitySourceList(
            items=items,
            total=len(items),
            entity_type=entity_type,
            entity_id=entity_id,
        )

    def get_source(
        self, db: Session, source_id: int
    ) -> Optional[EntitySourceResponse]:
        """단일 출처 조회"""
        source = db.query(EntitySource).filter(EntitySource.id == source_id).first()
        if not source:
            return None
        return self._to_response(source)

    def add_source(
        self,
        db: Session,
        entity_type: Literal["event", "popup"],
        entity_id: int,
        data: EntitySourceCreate,
    ) -> Optional[EntitySourceResponse]:
        """엔티티에 출처 추가"""
        # 엔티티 존재 확인
        if not self._entity_exists(db, entity_type, entity_id):
            logger.warning(f"{entity_type} {entity_id} not found")
            return None

        # 중복 출처 확인
        existing = (
            db.query(EntitySource)
            .filter(
                and_(
                    EntitySource.entity_type == entity_type,
                    EntitySource.entity_id == entity_id,
                    EntitySource.source_type == data.source_type,
                    EntitySource.source_id == data.source_id,
                )
            )
            .first()
        )

        if existing:
            logger.info(f"Source already exists: {existing.id}")
            return self._to_response(existing)

        # 첫 번째 출처인지 확인 (primary 설정용)
        source_count = (
            db.query(EntitySource)
            .filter(
                and_(
                    EntitySource.entity_type == entity_type,
                    EntitySource.entity_id == entity_id,
                )
            )
            .count()
        )

        is_primary = 1 if source_count == 0 else 0

        source = EntitySource(
            entity_type=entity_type,
            entity_id=entity_id,
            source_type=data.source_type,
            source_id=data.source_id,
            source_url=data.source_url,
            source_account=data.source_account,
            priority=data.priority,
            is_primary=is_primary,
            contributed_fields=(
                json.dumps(data.contributed_fields, ensure_ascii=False)
                if data.contributed_fields
                else None
            ),
            extracted_data=(
                json.dumps(data.extracted_data, ensure_ascii=False)
                if data.extracted_data
                else None
            ),
        )

        db.add(source)
        db.commit()
        db.refresh(source)

        # 엔티티의 source_count 업데이트
        self._update_entity_source_count(db, entity_type, entity_id)

        # primary인 경우 primary_source_id 업데이트
        if is_primary:
            self._update_entity_primary_source(db, entity_type, entity_id, source.id)

        return self._to_response(source)

    def remove_source(
        self,
        db: Session,
        entity_type: Literal["event", "popup"],
        entity_id: int,
        source_id: int,
    ) -> bool:
        """출처 제거"""
        source = (
            db.query(EntitySource)
            .filter(
                and_(
                    EntitySource.id == source_id,
                    EntitySource.entity_type == entity_type,
                    EntitySource.entity_id == entity_id,
                )
            )
            .first()
        )

        if not source:
            return False

        was_primary = source.is_primary == 1
        db.delete(source)
        db.commit()

        # source_count 업데이트
        self._update_entity_source_count(db, entity_type, entity_id)

        # primary였다면 다음 출처를 primary로 설정
        if was_primary:
            next_source = (
                db.query(EntitySource)
                .filter(
                    and_(
                        EntitySource.entity_type == entity_type,
                        EntitySource.entity_id == entity_id,
                    )
                )
                .order_by(EntitySource.priority.desc())
                .first()
            )
            if next_source:
                self.set_primary(db, entity_type, entity_id, next_source.id)
            else:
                self._update_entity_primary_source(db, entity_type, entity_id, None)

        return True

    def set_primary(
        self,
        db: Session,
        entity_type: Literal["event", "popup"],
        entity_id: int,
        source_id: int,
    ) -> Optional[EntitySourceResponse]:
        """대표 출처 변경"""
        # 기존 primary 해제
        db.query(EntitySource).filter(
            and_(
                EntitySource.entity_type == entity_type,
                EntitySource.entity_id == entity_id,
                EntitySource.is_primary == 1,
            )
        ).update({"is_primary": 0})

        # 새 primary 설정
        source = (
            db.query(EntitySource)
            .filter(
                and_(
                    EntitySource.id == source_id,
                    EntitySource.entity_type == entity_type,
                    EntitySource.entity_id == entity_id,
                )
            )
            .first()
        )

        if not source:
            db.rollback()
            return None

        source.is_primary = 1
        db.commit()
        db.refresh(source)

        # 엔티티의 primary_source_id 업데이트
        self._update_entity_primary_source(db, entity_type, entity_id, source_id)

        return self._to_response(source)

    def update_source(
        self,
        db: Session,
        source_id: int,
        data: EntitySourceUpdate,
    ) -> Optional[EntitySourceResponse]:
        """출처 정보 수정"""
        source = db.query(EntitySource).filter(EntitySource.id == source_id).first()
        if not source:
            return None

        update_data = data.model_dump(exclude_unset=True)

        if "contributed_fields" in update_data:
            update_data["contributed_fields"] = (
                json.dumps(update_data["contributed_fields"], ensure_ascii=False)
                if update_data["contributed_fields"]
                else None
            )

        for field, value in update_data.items():
            setattr(source, field, value)

        db.commit()
        db.refresh(source)

        return self._to_response(source)

    def _entity_exists(
        self, db: Session, entity_type: Literal["event", "popup"], entity_id: int
    ) -> bool:
        """엔티티 존재 확인"""
        if entity_type == "event":
            return db.query(Event).filter(Event.id == entity_id).first() is not None
        elif entity_type == "popup":
            return db.query(Popup).filter(Popup.id == entity_id).first() is not None
        return False

    def _update_entity_source_count(
        self, db: Session, entity_type: Literal["event", "popup"], entity_id: int
    ) -> None:
        """엔티티의 source_count 업데이트"""
        count = (
            db.query(EntitySource)
            .filter(
                and_(
                    EntitySource.entity_type == entity_type,
                    EntitySource.entity_id == entity_id,
                )
            )
            .count()
        )

        if entity_type == "event":
            db.query(Event).filter(Event.id == entity_id).update(
                {"source_count": count}
            )
        elif entity_type == "popup":
            db.query(Popup).filter(Popup.id == entity_id).update(
                {"source_count": count}
            )
        db.commit()

    def _update_entity_primary_source(
        self,
        db: Session,
        entity_type: Literal["event", "popup"],
        entity_id: int,
        primary_source_id: Optional[int],
    ) -> None:
        """엔티티의 primary_source_id 업데이트"""
        if entity_type == "event":
            db.query(Event).filter(Event.id == entity_id).update(
                {"primary_source_id": primary_source_id}
            )
        elif entity_type == "popup":
            db.query(Popup).filter(Popup.id == entity_id).update(
                {"primary_source_id": primary_source_id}
            )
        db.commit()

    def _to_response(self, source: EntitySource) -> EntitySourceResponse:
        """EntitySource 모델을 Response로 변환"""
        return EntitySourceResponse(
            id=source.id,
            entity_type=source.entity_type,
            entity_id=source.entity_id,
            source_type=source.source_type,
            source_id=source.source_id,
            source_url=source.source_url,
            source_account=source.source_account,
            priority=source.priority,
            is_primary=source.is_primary == 1,
            contributed_fields=source.contributed_fields,
            extracted_data=source.extracted_data,
            discovered_at=source.discovered_at,
            created_at=source.created_at,
        )


entity_source_service = EntitySourceService()

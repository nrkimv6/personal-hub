"""Manual event merge service."""

import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models.entity_source import EntitySource
from app.models.event import Event
from app.schemas.duplicate_merge import (
    MERGE_FIELD_WHITELIST,
    EventDuplicateSummary,
    MergeExecuteRequest,
    MergeExecuteResponse,
    MergeFieldComparison,
    MergePreviewResponse,
)
from app.services.duplicate_detection_service import duplicate_detection_service


MERGE_FIELDS: list[tuple[str, str]] = [
    ("title", "제목"),
    ("event_url", "참여 URL"),
    ("url_type", "URL 유형"),
    ("additional_urls", "추가 URL"),
    ("event_start", "시작일"),
    ("event_end", "종료일"),
    ("announcement_date", "발표일"),
    ("organizer", "주최"),
    ("summary", "요약"),
    ("body_text", "본문"),
    ("prizes", "경품"),
    ("winner_count", "당첨자 수"),
    ("purchase_required", "구매 조건"),
    ("location_venue", "장소"),
    ("location_address", "주소"),
    ("source_url", "출처 URL"),
    ("source_note", "출처 메모"),
    ("user_note", "사용자 메모"),
    ("is_offline", "오프라인"),
]


class EventMergeService:
    """Preview and execute manual merges for Event rows."""

    def preview_merge(self, db: Session, primary_id: int, secondary_id: int) -> MergePreviewResponse:
        primary, secondary = self._load_merge_pair(db, primary_id, secondary_id)
        similarity = duplicate_detection_service.calculate_event_similarity(primary, secondary)
        fields = [
            MergeFieldComparison(
                field=field,
                label=label,
                primary_value=self._jsonable(getattr(primary, field, None)),
                secondary_value=self._jsonable(getattr(secondary, field, None)),
                selected_source="primary",
            )
            for field, label in MERGE_FIELDS
        ]
        return MergePreviewResponse(
            primary_id=primary.id,
            secondary_id=secondary.id,
            similarity=round(similarity, 4),
            matched_fields=duplicate_detection_service.get_event_matched_fields(primary, secondary),
            primary=self._event_summary(primary),
            secondary=self._event_summary(secondary),
            fields=fields,
            primary_source_count=self._source_count(db, primary.id),
            secondary_source_count=self._source_count(db, secondary.id),
        )

    def execute_merge(self, db: Session, request: MergeExecuteRequest) -> MergeExecuteResponse:
        if request.entity_type != "event":
            raise ValueError("Only event merge is supported")
        unknown = sorted(set(request.field_selections) - MERGE_FIELD_WHITELIST)
        if unknown:
            raise ValueError(f"Unsupported merge fields: {', '.join(unknown)}")

        primary, secondary = self._load_merge_pair(db, request.primary_id, request.secondary_id)
        if secondary.status == "disabled":
            raise ValueError("Secondary event is already disabled")

        updated_fields: list[str] = []
        moved_source_count = 0
        try:
            for field, source in request.field_selections.items():
                if source != "secondary":
                    continue
                setattr(primary, field, getattr(secondary, field, None))
                updated_fields.append(field)

            moved_source_count = self._move_sources(db, primary.id, secondary.id)
            db.flush()
            primary.merged_from = json.dumps(
                self._merged_from_ids(primary.merged_from, secondary.id),
                ensure_ascii=False,
            )
            primary.source_count = self._source_count(db, primary.id)
            primary.primary_source_id = self._primary_source_id(db, primary.id)
            primary.updated_at = datetime.now()

            secondary.status = "disabled"
            secondary.source_count = self._source_count(db, secondary.id)
            secondary.primary_source_id = self._primary_source_id(db, secondary.id)
            secondary.updated_at = datetime.now()

            db.commit()
        except Exception:
            db.rollback()
            raise

        db.refresh(primary)
        db.refresh(secondary)
        return MergeExecuteResponse(
            merged_id=primary.id,
            disabled_id=secondary.id,
            source_count=primary.source_count or 0,
            moved_source_count=moved_source_count,
            merged_from=self._merged_from_ids(primary.merged_from),
            updated_fields=updated_fields,
            secondary_status=secondary.status,
            primary=self._event_summary(primary),
        )

    def _load_merge_pair(self, db: Session, primary_id: int, secondary_id: int) -> tuple[Event, Event]:
        if primary_id == secondary_id:
            raise ValueError("Primary and secondary events must be different")
        primary = db.query(Event).filter(Event.id == primary_id).first()
        secondary = db.query(Event).filter(Event.id == secondary_id).first()
        if not primary or not secondary:
            raise ValueError("Event not found")
        if primary.status == "disabled":
            raise ValueError("Primary event is disabled")
        if secondary.status == "disabled":
            raise ValueError("Secondary event is already disabled")
        return primary, secondary

    def _move_sources(self, db: Session, primary_id: int, secondary_id: int) -> int:
        sources = (
            db.query(EntitySource)
            .filter(
                EntitySource.entity_type == "event",
                EntitySource.entity_id == secondary_id,
            )
            .order_by(EntitySource.is_primary.desc(), EntitySource.priority.desc(), EntitySource.id.asc())
            .all()
        )
        moved = 0
        for source in sources:
            duplicate = self._find_duplicate_source(db, primary_id, source)
            if duplicate:
                db.delete(source)
                continue
            source.entity_id = primary_id
            source.is_primary = 0
            moved += 1
        return moved

    def _find_duplicate_source(
        self,
        db: Session,
        primary_id: int,
        source: EntitySource,
    ) -> EntitySource | None:
        query = db.query(EntitySource).filter(
            and_(
                EntitySource.entity_type == "event",
                EntitySource.entity_id == primary_id,
                EntitySource.source_type == source.source_type,
            )
        )
        if source.source_id is not None:
            return query.filter(EntitySource.source_id == source.source_id).first()
        if source.source_url:
            return query.filter(EntitySource.source_url == source.source_url).first()
        return query.filter(EntitySource.source_id.is_(None), EntitySource.source_url.is_(None)).first()

    def _source_count(self, db: Session, event_id: int) -> int:
        return (
            db.query(EntitySource)
            .filter(EntitySource.entity_type == "event", EntitySource.entity_id == event_id)
            .count()
        )

    def _primary_source_id(self, db: Session, event_id: int) -> int | None:
        source = (
            db.query(EntitySource)
            .filter(EntitySource.entity_type == "event", EntitySource.entity_id == event_id)
            .order_by(EntitySource.is_primary.desc(), EntitySource.priority.desc(), EntitySource.id.asc())
            .first()
        )
        if not source:
            return None
        if source.is_primary != 1:
            source.is_primary = 1
        return source.id

    def _merged_from_ids(self, raw_value: Any, append_id: int | None = None) -> list[int]:
        values: list[int] = []
        if raw_value:
            try:
                parsed = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
            except (TypeError, json.JSONDecodeError):
                parsed = []
            if isinstance(parsed, list):
                for value in parsed:
                    try:
                        values.append(int(value))
                    except (TypeError, ValueError):
                        continue
        if append_id is not None:
            values.append(int(append_id))
        return sorted(set(values))

    def _event_summary(self, event: Event) -> EventDuplicateSummary:
        return EventDuplicateSummary(
            id=event.id,
            title=event.title,
            status=event.status,
            organizer=event.organizer,
            event_url=event.event_url,
            event_start=event.event_start,
            event_end=event.event_end,
            source_type=event.source_type,
            source_count=event.source_count or 0,
            created_at=event.created_at,
        )

    def _jsonable(self, value: Any) -> Any:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return value


event_merge_service = EventMergeService()

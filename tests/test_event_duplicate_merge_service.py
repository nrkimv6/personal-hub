import json
from datetime import date, timedelta

import pytest

from app.models import DismissedDuplicate, EntitySource, Event
from app.schemas.duplicate_merge import MergeExecuteRequest
from app.services.duplicate_detection_service import duplicate_detection_service
from app.services.event_merge_service import event_merge_service


def _event(test_db_session, title: str, **kwargs) -> Event:
    data = {
        "title": title,
        "event_type": "event",
        "status": "active",
        "source_type": "manual",
        "event_start": date.today(),
        "event_end": date.today() + timedelta(days=7),
        "organizer": "테스트브랜드",
        "prizes": ["쿠폰", "굿즈"],
    }
    data.update(kwargs)
    event = Event(**data)
    test_db_session.add(event)
    test_db_session.commit()
    test_db_session.refresh(event)
    return event


def _source(test_db_session, event_id: int, source_type: str = "web", source_id: int | None = None) -> EntitySource:
    source = EntitySource(
        entity_type="event",
        entity_id=event_id,
        source_type=source_type,
        source_id=source_id,
        source_url=f"https://example.com/source/{source_type}/{source_id or event_id}",
        priority=50,
        is_primary=1 if source_id == 1 else 0,
    )
    test_db_session.add(source)
    test_db_session.commit()
    test_db_session.refresh(source)
    return source


def test_find_duplicate_candidates_R_returns_similarity_sorted_active_pairs(test_db_session):
    first = _event(test_db_session, "정렬 후보 A", organizer="정렬브랜드")
    second = _event(test_db_session, "정렬 후보 B", organizer="정렬브랜드")

    candidates = duplicate_detection_service.find_duplicate_candidates(
        test_db_session,
        entity_type="event",
        min_similarity=0.5,
        max_similarity=1.0,
        limit=20,
    )

    pair_ids = {(item.entity1_id, item.entity2_id) for item in candidates}
    assert DismissedDuplicate.ordered_pair(first.id, second.id) in pair_ids
    assert candidates == sorted(candidates, key=lambda item: item.similarity, reverse=True)
    matched = next(item for item in candidates if {item.entity1_id, item.entity2_id} == {first.id, second.id})
    assert "organizer" in matched.matched_fields
    assert "event_period" in matched.matched_fields


def test_find_duplicate_candidates_B_excludes_disabled_and_dismissed_pairs(test_db_session):
    active_a = _event(test_db_session, "dismiss 후보 A", organizer="dismiss브랜드")
    active_b = _event(test_db_session, "dismiss 후보 B", organizer="dismiss브랜드")
    disabled = _event(test_db_session, "disabled 후보", organizer="dismiss브랜드", status="disabled")
    pair = DismissedDuplicate.ordered_pair(active_a.id, active_b.id)
    test_db_session.add(DismissedDuplicate(entity_type="event", entity1_id=pair[0], entity2_id=pair[1]))
    test_db_session.commit()

    candidates = duplicate_detection_service.find_duplicate_candidates(
        test_db_session,
        entity_type="event",
        min_similarity=0.5,
        max_similarity=1.0,
        limit=50,
    )

    pairs = [{item.entity1_id, item.entity2_id} for item in candidates]
    assert {active_a.id, active_b.id} not in pairs
    assert all(disabled.id not in pair_ids for pair_ids in pairs)


def test_preview_merge_R_returns_fields_and_sources(test_db_session):
    primary = _event(test_db_session, "preview primary")
    secondary = _event(test_db_session, "preview secondary")
    _source(test_db_session, primary.id, source_id=1)
    _source(test_db_session, secondary.id, source_id=2)

    preview = event_merge_service.preview_merge(test_db_session, primary.id, secondary.id)

    assert preview.primary_id == primary.id
    assert preview.secondary_id == secondary.id
    assert preview.primary_source_count == 1
    assert preview.secondary_source_count == 1
    assert {field.field for field in preview.fields} >= {"title", "organizer", "prizes"}


def test_execute_merge_R_moves_selected_fields_sources_and_disables_secondary(test_db_session):
    primary = _event(test_db_session, "primary before", summary="keep")
    secondary = _event(test_db_session, "secondary title", summary="take me")
    _source(test_db_session, primary.id, source_id=10)
    _source(test_db_session, secondary.id, source_id=11)

    result = event_merge_service.execute_merge(
        test_db_session,
        MergeExecuteRequest(
            primary_id=primary.id,
            secondary_id=secondary.id,
            field_selections={"title": "secondary", "summary": "secondary"},
        ),
    )

    test_db_session.refresh(primary)
    test_db_session.refresh(secondary)
    assert result.merged_id == primary.id
    assert result.disabled_id == secondary.id
    assert result.moved_source_count == 1
    assert primary.title == "secondary title"
    assert primary.summary == "take me"
    assert secondary.status == "disabled"
    assert secondary.id in json.loads(primary.merged_from)
    assert test_db_session.query(EntitySource).filter_by(entity_type="event", entity_id=primary.id).count() == 2


def test_execute_merge_E_rejects_same_or_missing_or_disabled_secondary(test_db_session):
    primary = _event(test_db_session, "reject primary")
    disabled = _event(test_db_session, "reject disabled", status="disabled")

    with pytest.raises(ValueError):
        event_merge_service.execute_merge(
            test_db_session,
            MergeExecuteRequest(primary_id=primary.id, secondary_id=primary.id),
        )
    with pytest.raises(ValueError):
        event_merge_service.execute_merge(
            test_db_session,
            MergeExecuteRequest(primary_id=primary.id, secondary_id=999999),
        )
    with pytest.raises(ValueError):
        event_merge_service.execute_merge(
            test_db_session,
            MergeExecuteRequest(primary_id=primary.id, secondary_id=disabled.id),
        )


def test_execute_merge_C_is_idempotent_for_merged_from_and_sources(test_db_session):
    primary = _event(test_db_session, "idempotent primary", merged_from="not-json")
    secondary = _event(test_db_session, "idempotent secondary")
    _source(test_db_session, primary.id, source_type="web", source_id=77)
    _source(test_db_session, secondary.id, source_type="web", source_id=77)

    result = event_merge_service.execute_merge(
        test_db_session,
        MergeExecuteRequest(primary_id=primary.id, secondary_id=secondary.id),
    )

    test_db_session.refresh(primary)
    assert result.moved_source_count == 0
    assert json.loads(primary.merged_from) == [secondary.id]
    assert test_db_session.query(EntitySource).filter_by(entity_type="event", entity_id=primary.id).count() == 1

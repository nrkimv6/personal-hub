from datetime import date, timedelta

from sqlalchemy import text

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
        "event_end": date.today() + timedelta(days=5),
        "organizer": "통합브랜드",
        "prizes": ["기프티콘"],
    }
    data.update(kwargs)
    event = Event(**data)
    test_db_session.add(event)
    test_db_session.commit()
    test_db_session.refresh(event)
    return event


def _source(test_db_session, event_id: int, source_id: int) -> None:
    test_db_session.add(
        EntitySource(
            entity_type="event",
            entity_id=event_id,
            source_type="web",
            source_id=source_id,
            source_url=f"https://example.com/integration/{source_id}",
        )
    )
    test_db_session.commit()


def test_dismissed_duplicates_schema_exists_with_unique_index(test_db_session):
    table = test_db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='dismissed_duplicates'")
    ).fetchone()
    indexes = test_db_session.execute(text("PRAGMA index_list(dismissed_duplicates)")).fetchall()

    assert table is not None
    assert any("uq_dismissed_duplicates_pair" in row[1] or row[2] for row in indexes)


def test_event_duplicate_merge_flow_reads_back_db_state(test_db_session):
    primary = _event(test_db_session, "integration primary", summary="old summary")
    secondary = _event(test_db_session, "integration secondary", summary="new summary")
    _source(test_db_session, primary.id, 101)
    _source(test_db_session, secondary.id, 102)

    candidates = duplicate_detection_service.find_duplicate_candidates(
        test_db_session,
        entity_type="event",
        min_similarity=0.5,
        max_similarity=1.0,
        limit=50,
    )
    assert any({candidate.entity1_id, candidate.entity2_id} == {primary.id, secondary.id} for candidate in candidates)

    preview = event_merge_service.preview_merge(test_db_session, primary.id, secondary.id)
    assert preview.primary_source_count == 1
    assert preview.secondary_source_count == 1

    result = event_merge_service.execute_merge(
        test_db_session,
        MergeExecuteRequest(
            primary_id=primary.id,
            secondary_id=secondary.id,
            field_selections={"summary": "secondary"},
        ),
    )

    test_db_session.refresh(primary)
    test_db_session.refresh(secondary)
    assert result.disabled_id == secondary.id
    assert secondary.status == "disabled"
    assert primary.summary == "new summary"
    assert secondary.id in result.merged_from
    assert test_db_session.query(EntitySource).filter_by(entity_type="event", entity_id=primary.id).count() == 2

    after = duplicate_detection_service.find_duplicate_candidates(
        test_db_session,
        entity_type="event",
        min_similarity=0.5,
        max_similarity=1.0,
        limit=50,
    )
    assert all({candidate.entity1_id, candidate.entity2_id} != {primary.id, secondary.id} for candidate in after)


def test_dismiss_flow_excludes_candidate_pair(test_db_session):
    first = _event(test_db_session, "integration dismiss first", organizer="dismiss integration")
    second = _event(test_db_session, "integration dismiss second", organizer="dismiss integration")
    pair = DismissedDuplicate.ordered_pair(first.id, second.id)
    test_db_session.add(DismissedDuplicate(entity_type="event", entity1_id=pair[0], entity2_id=pair[1]))
    test_db_session.commit()

    candidates = duplicate_detection_service.find_duplicate_candidates(
        test_db_session,
        entity_type="event",
        min_similarity=0.5,
        max_similarity=1.0,
        limit=50,
    )

    assert all({candidate.entity1_id, candidate.entity2_id} != {first.id, second.id} for candidate in candidates)

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.event import Event
from app.models.instagram_post import InstagramPost
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.worker.worker import LLMWorker
from scripts.diagnostics.instagram_event_incident_report import build_window, collect_funnel_metrics
from scripts.diagnostics.recover_instagram_llm_missing_events import build_candidate, recover_candidate


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def worker():
    instance = LLMWorker()
    instance._update_worker_state = MagicMock()
    instance._increment_processed = MagicMock()
    return instance


@pytest.mark.asyncio
async def test_instagram_envelope_result_creates_event_and_completes_request(db, worker):
    post = InstagramPost(
        id=6041,
        post_id="p6041",
        account="onegrove",
        url="https://instagram.com/p/test",
        caption="event caption",
        images=[{"src": "https://example.com/thumb.jpg"}],
    )
    request = LLMRequest(
        id=14074,
        caller_type="instagram",
        caller_id="6041",
        prompt="test",
        status="pending",
    )
    db.add_all([post, request])
    db.commit()

    service = LLMService(db)
    service.resolve_provider_model = MagicMock(return_value=("claude", "claude-haiku-4-5"))
    service.execute_llm = MagicMock(
        return_value={
            "success": True,
            "result": {
                "tag": "이벤트",
                "summary": "원그로브 이벤트",
                "organizer": "원그로브",
                "urls": ["https://example.com/form"],
                "event_period": {"start": "2026-04-17", "end": "2026-04-17"},
                "announcement_date": None,
                "prizes": [],
                "winner_count": None,
                "purchase_required": "아니오",
            },
            "raw_response": json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "result": (
                        "```json\n"
                        '{"tag":"이벤트","summary":"원그로브 이벤트","organizer":"원그로브","urls":["https://example.com/form"],'
                        '"event_period":{"start":"2026-04-17","end":"2026-04-17"},"announcement_date":null,'
                        '"prizes":[],"winner_count":null,"purchase_required":"아니오"}\n'
                        "```"
                    ),
                    "session_id": "session-1",
                },
                ensure_ascii=False,
            ),
            "claude_session_id": "session-1",
        }
    )

    await worker._execute_request(request, db, service)

    db.refresh(request)
    db.refresh(post)

    event = db.query(Event).filter(Event.source_instagram_post_id == 6041).first()
    assert event is not None
    assert event.summary == "원그로브 이벤트"
    assert post.classified_type == "event"
    assert post.classified_id == event.id
    assert request.status == "completed"
    assert request.claude_session_id == "session-1"
    assert json.loads(request.result)["tag"] == "이벤트"
    assert "session-1" in request.raw_response
    service.execute_llm.assert_called_once()
    worker._increment_processed.assert_called_once()


@pytest.mark.asyncio
async def test_instagram_invalid_payload_marks_failed_without_completed(db, worker):
    post = InstagramPost(
        id=7001,
        post_id="p7001",
        account="broken",
        caption="broken caption",
    )
    request = LLMRequest(
        id=7002,
        caller_type="instagram",
        caller_id="7001",
        prompt="test",
        status="pending",
    )
    db.add_all([post, request])
    db.commit()

    service = LLMService(db)
    service.resolve_provider_model = MagicMock(return_value=("claude", "claude-haiku-4-5"))
    service.execute_llm = MagicMock(
        return_value={
            "success": True,
            "result": {"type": "result", "subtype": "success", "result": "not-json"},
            "raw_response": '{"type":"result","subtype":"success","result":"not-json"}',
        }
    )

    await worker._execute_request(request, db, service)

    db.refresh(request)
    db.refresh(post)
    assert request.status == "failed"
    assert request.error_message is not None
    assert post.classified_type is None
    assert db.query(Event).filter(Event.source_instagram_post_id == 7001).count() == 0
    worker._increment_processed.assert_not_called()


@pytest.mark.asyncio
async def test_instagram_mojibake_payload_marks_failed_without_completed(db, worker):
    post = InstagramPost(
        id=7101,
        post_id="p7101",
        account="broken",
        url="https://instagram.com/p/7101",
        caption="caption",
    )
    request = LLMRequest(
        id=7102,
        caller_type="instagram",
        caller_id="7101",
        prompt="test",
        status="pending",
    )
    db.add_all([post, request])
    db.commit()

    service = LLMService(db)
    service.resolve_provider_model = MagicMock(return_value=("claude", "claude-haiku-4-5"))
    service.execute_llm = MagicMock(
        return_value={
            "success": True,
            "result": {
                "tag": "\ufffd\u013a\u00ba\uFFFD\u01AE",
                "summary": "깨진 응답",
                "urls": [],
                "event_period": {"start": "2026-04-17", "end": "2026-04-17"},
                "prizes": [],
                "winner_count": None,
                "purchase_required": "아니오",
            },
            "raw_response": '{"tag":"\ufffd\u013a\u00ba\uFFFD\u01AE"}',
            "claude_session_id": "session-broken",
        }
    )

    await worker._execute_request(request, db, service)

    db.refresh(request)
    assert request.status == "failed"
    assert request.error_message == "encoding_mojibake"
    assert db.query(Event).filter(Event.source_instagram_post_id == 7101).count() == 0


def test_legacy_completed_request_can_be_recovered_from_raw_envelope(db):
    post = InstagramPost(
        id=8001,
        post_id="p8001",
        account="legacy",
        url="https://instagram.com/p/legacy",
        caption="legacy caption",
    )
    request = LLMRequest(
        id=8002,
        caller_type="instagram",
        caller_id="8001",
        prompt="test",
        status="completed",
        request_source="instagram_event",
        result=json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "result": (
                    "```json\n"
                    '{"tag":"이벤트","summary":"legacy repaired","organizer":"legacy","urls":[],"event_period":{"start":"2026-04-17","end":"2026-04-17"}}\n'
                    "```"
                ),
            },
            ensure_ascii=False,
        ),
    )
    db.add_all([post, request])
    db.commit()

    candidate = build_candidate(db, request)
    assert candidate is not None
    assert candidate.action == "create"

    outcome = recover_candidate(db, candidate)
    db.refresh(post)

    assert outcome.changed is True
    assert outcome.action == "create"
    assert post.classified_type == "event"
    assert post.classified_id is not None
    repaired_event = db.query(Event).filter(Event.id == post.classified_id).first()
    assert repaired_event is not None
    assert repaired_event.summary == "legacy repaired"


def test_repairable_mojibake_candidate_creates_event(db):
    repaired_tag = "\uc774\ubca4\ud2b8"
    repaired_summary = "\uc218\ubcf5 \uc774\ubca4\ud2b8"
    mojibake_tag = repaired_tag.encode("utf-8").decode("latin1")
    mojibake_summary = repaired_summary.encode("utf-8").decode("latin1")

    post = InstagramPost(
        id=8101,
        post_id="p8101",
        account="legacy",
        url="https://instagram.com/p/8101",
        caption="legacy caption",
    )
    request = LLMRequest(
        id=8102,
        caller_type="instagram",
        caller_id="8101",
        prompt="test",
        status="completed",
        request_source="instagram_event",
        result=json.dumps(
            {
                "tag": mojibake_tag,
                "summary": mojibake_summary,
                "urls": [],
                "event_period": {"start": "2026-04-17", "end": "2026-04-17"},
            },
            ensure_ascii=False,
        ),
    )
    db.add_all([post, request])
    db.commit()

    candidate = build_candidate(db, request)
    outcome = recover_candidate(db, candidate)
    repaired_event = db.query(Event).filter(Event.source_instagram_post_id == 8101).first()

    assert candidate is not None
    assert candidate.action == "repair"
    assert outcome.changed is True
    assert outcome.action == "repair"
    assert repaired_event is not None
    assert repaired_event.summary == repaired_summary


def test_completed_no_event_bucket_matches_recovery_candidate_state(db):
    post = InstagramPost(
        id=9001,
        post_id="p9001",
        account="bucket",
        url="https://instagram.com/p/bucket",
        caption="caption",
        created_at=datetime(2026, 4, 17, 9, 0, 0),
    )
    request = LLMRequest(
        id=9002,
        caller_type="instagram",
        caller_id="9001",
        prompt="test",
        status="completed",
        request_source="instagram_event",
        requested_at=datetime(2026, 4, 17, 10, 0, 0),
        processed_at=datetime(2026, 4, 17, 10, 1, 0),
        result=json.dumps(
            {
                "tag": "이벤트",
                "summary": "still missing",
                "urls": [],
                "event_period": {"start": "2026-04-17", "end": "2026-04-17"},
            },
            ensure_ascii=False,
        ),
    )
    db.add_all([post, request])
    db.commit()

    candidate = build_candidate(db, request)
    metrics = {
        row.metric: row
        for row in collect_funnel_metrics(
            db,
            build_window("incident", "2026-04-17", "2026-04-17"),
        )
    }

    assert candidate is not None
    assert candidate.action == "create"
    assert metrics["completed_event_missing"].count == 1
    assert metrics["completed_event_missing"].sample_ids == [9001]
    assert metrics["completed_mojibake_requests"].count == 0

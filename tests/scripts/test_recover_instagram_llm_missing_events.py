"""Unit tests for scripts/diagnostics/recover_instagram_llm_missing_events.py."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "diagnostics"))

import recover_instagram_llm_missing_events as m  # noqa: E402
from app.models.event import Event  # noqa: E402
from app.models.instagram_post import InstagramPost  # noqa: E402


def make_session():
    engine = create_engine("sqlite:///:memory:")
    InstagramPost.__table__.create(bind=engine, checkfirst=True)
    Event.__table__.create(bind=engine, checkfirst=True)
    session = sessionmaker(bind=engine)()
    return session, engine


def test_normalize_payload_unwraps_outer_envelope_result_string():
    raw = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "result": (
                "```json\n"
                '{"tag":"이벤트","summary":"테스트 이벤트","urls":[],"event_period":{"start":"2026-04-17","end":"2026-04-17"}}\n'
                "```"
            ),
        },
        ensure_ascii=False,
    )

    payload = m.normalize_payload(raw, None)

    assert payload is not None
    assert payload["tag"] == "이벤트"
    assert payload["summary"] == "테스트 이벤트"


def test_normalize_payload_falls_back_to_raw_response():
    payload = m.normalize_payload(
        None,
        '{"result":{"tag":"이벤트","summary":"raw fallback","urls":[],"event_period":null},"type":"result"}',
    )

    assert payload is not None
    assert payload["summary"] == "raw fallback"


def test_recover_candidate_creates_event_and_updates_post():
    session, engine = make_session()
    try:
        post = InstagramPost(
            id=6041,
            post_id="abc",
            account="onegrove",
            url="https://instagram.com/p/test",
            caption="caption",
            images=[{"src": "https://example.com/thumb.jpg"}],
        )
        session.add(post)
        session.commit()

        candidate = m.Candidate(
            request_id=14074,
            post_id=6041,
            request_source="instagram_event",
            processed_at=datetime(2026, 4, 14, 17, 7, 35),
            account="onegrove",
            summary="원그로브 이벤트",
            organizer="원그로브",
            event_start=datetime(2026, 4, 17).date(),
            event_end=datetime(2026, 4, 17).date(),
            event_url=None,
            existing_event_id=None,
            classified_type=None,
            classified_id=None,
            action="create",
            reason="missing_event_row",
            payload={
                "tag": "이벤트",
                "summary": "원그로브 이벤트",
                "organizer": "원그로브",
                "urls": [],
                "event_period": {"start": "2026-04-17", "end": "2026-04-17"},
                "announcement_date": None,
                "prizes": [],
                "winner_count": None,
                "purchase_required": "아니오",
            },
        )

        outcome = m.recover_candidate(session, candidate)

        assert outcome.changed is True
        assert outcome.action == "create"
        repaired_post = session.query(InstagramPost).filter(InstagramPost.id == 6041).first()
        assert repaired_post.classified_type == "event"
        assert repaired_post.classified_id is not None

        event = session.query(Event).filter(Event.id == repaired_post.classified_id).first()
        assert event is not None
        assert event.source_instagram_post_id == 6041
        assert event.summary == "원그로브 이벤트"
    finally:
        session.close()
        engine.dispose()


def test_recover_candidate_skips_duplicate_url_by_default():
    session, engine = make_session()
    try:
        original_post = InstagramPost(id=100, post_id="p100", account="dup", caption="a")
        target_post = InstagramPost(id=200, post_id="p200", account="dup2", caption="b")
        session.add_all([original_post, target_post])
        session.flush()
        session.add(
            Event(
                title="existing",
                event_type="event",
                event_url="https://event.example.com/form",
                source_type="instagram",
                source_instagram_post_id=100,
                source_instagram_account="dup",
            )
        )
        session.commit()

        candidate = m.Candidate(
            request_id=2,
            post_id=200,
            request_source="instagram_event",
            processed_at=None,
            account="dup2",
            summary="new",
            organizer=None,
            event_start=None,
            event_end=None,
            event_url="https://event.example.com/form",
            existing_event_id=None,
            classified_type=None,
            classified_id=None,
            action="create",
            reason="missing_event_row",
            payload={"tag": "이벤트", "summary": "new", "urls": ["https://event.example.com/form"]},
        )

        outcome = m.recover_candidate(session, candidate, allow_duplicate_url=False)

        assert outcome.changed is False
        assert outcome.action == "skip"
        assert outcome.reason.startswith("duplicate_url_event:")
        target_post = session.query(InstagramPost).filter(InstagramPost.id == 200).first()
        assert target_post.classified_id is None
    finally:
        session.close()
        engine.dispose()

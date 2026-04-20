"""Unit tests for scripts/diagnostics/recover_instagram_llm_missing_events.py."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "diagnostics"))

import recover_instagram_llm_missing_events as m  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.event import Event  # noqa: E402
from app.models.instagram_post import InstagramPost  # noqa: E402
from app.modules.claude_worker.models.llm_request import LLMRequest  # noqa: E402


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


def test_normalize_payload_repairs_cp949_roundtrip_R():
    repaired_tag = "\uc774\ubca4\ud2b8"
    repaired_summary = "\ud14c\uc2a4\ud2b8 \uc774\ubca4\ud2b8"
    mojibake_tag = repaired_tag.encode("utf-8").decode("latin1")
    mojibake_summary = repaired_summary.encode("utf-8").decode("latin1")
    raw = json.dumps(
        {
            "tag": mojibake_tag,
            "summary": mojibake_summary,
            "urls": [],
            "event_period": {"start": "2026-04-17", "end": "2026-04-17"},
        },
        ensure_ascii=False,
    )

    payload = m.normalize_payload(raw, None)

    assert payload is not None
    assert payload["tag"] == repaired_tag
    assert payload["summary"] == repaired_summary


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


def test_recover_candidate_relinks_existing_event():
    session, engine = make_session()
    try:
        post = InstagramPost(id=300, post_id="p300", account="acc", caption="caption")
        session.add(post)
        session.flush()
        event = Event(
            title="existing",
            event_type="event",
            source_type="instagram",
            source_instagram_post_id=300,
            source_instagram_account="acc",
        )
        session.add(event)
        session.commit()

        candidate = m.Candidate(
            request_id=3,
            post_id=300,
            request_source="instagram_event",
            processed_at=datetime(2026, 4, 14, 17, 7, 35),
            account="acc",
            summary="existing",
            organizer=None,
            event_start=None,
            event_end=None,
            event_url=None,
            existing_event_id=event.id,
            classified_type=None,
            classified_id=None,
            action="relink",
            reason="event_exists_but_post_link_missing",
            payload={"tag": "이벤트", "summary": "existing", "urls": []},
        )

        outcome = m.recover_candidate(session, candidate)

        session.refresh(post)
        assert outcome.changed is True
        assert outcome.action == "relink"
        assert post.classified_type == "event"
        assert post.classified_id == event.id
    finally:
        session.close()
        engine.dispose()


def test_build_candidate_marks_requeue_needed_E():
    session, engine = _make_full_session()
    try:
        post = InstagramPost(
            id=400,
            post_id="p400",
            account="broken",
            url="https://instagram.com/p/400",
            caption="caption",
            images=[],
        )
        request = LLMRequest(
            id=4001,
            caller_type="instagram",
            caller_id="400",
            prompt="test",
            status="completed",
            request_source="instagram_event",
            result=json.dumps(
                {
                    "tag": "\ufffd\u013a\u00ba\uFFFD\u01AE",
                    "summary": "깨진 응답",
                    "urls": [],
                    "event_period": {"start": "2026-04-17", "end": "2026-04-17"},
                },
                ensure_ascii=False,
            ),
            raw_response='{"tag":"\ufffd\u013a\u00ba\uFFFD\u01AE"}',
        )
        session.add_all([post, request])
        session.commit()

        candidate = m.build_candidate(session, request)

        assert candidate is not None
        assert candidate.action == "requeue"
        assert candidate.reason == "requeue_required"
    finally:
        session.close()
        engine.dispose()


def test_recover_candidate_uses_repaired_payload_Co():
    session, engine = make_session()
    try:
        post = InstagramPost(
            id=601,
            post_id="p601",
            account="acc",
            url="https://instagram.com/p/601",
            caption="caption",
            images=[{"src": "https://example.com/thumb.jpg"}],
        )
        session.add(post)
        session.commit()

        repaired_tag = "\uc774\ubca4\ud2b8"
        repaired_summary = "\uc218\ubcf5 \uc774\ubca4\ud2b8"
        candidate = m.Candidate(
            request_id=6011,
            post_id=601,
            request_source="instagram_event",
            processed_at=datetime(2026, 4, 14, 17, 7, 35),
            account="acc",
            summary=repaired_summary,
            organizer=None,
            event_start=datetime(2026, 4, 17).date(),
            event_end=datetime(2026, 4, 17).date(),
            event_url=None,
            existing_event_id=None,
            classified_type=None,
            classified_id=None,
            action="repair",
            reason="repairable_mojibake",
            payload={
                "tag": repaired_tag,
                "summary": repaired_summary,
                "urls": [],
                "event_period": {"start": "2026-04-17", "end": "2026-04-17"},
                "announcement_date": None,
                "prizes": [],
                "winner_count": None,
                "purchase_required": "아니오",
            },
        )

        outcome = m.recover_candidate(session, candidate)

        repaired_post = session.query(InstagramPost).filter(InstagramPost.id == 601).first()
        event = session.query(Event).filter(Event.id == repaired_post.classified_id).first()
        assert outcome.changed is True
        assert outcome.action == "repair"
        assert outcome.reason == "repairable_mojibake"
        assert event is not None
        assert event.summary == repaired_summary
    finally:
        session.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# 날짜 범위 필터 TC (Phase 2 Task 4)
# ---------------------------------------------------------------------------

def _make_full_session():
    """LLMRequest 포함 전체 테이블 SQLite in-memory 세션."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    return session, engine


def _make_request_with_processed_at(session, req_id: int, post_id: int, processed_at: datetime):
    """post + completed LLM request(태그=이벤트) 쌍 생성 헬퍼."""
    payload_json = json.dumps({
        "type": "result",
        "subtype": "success",
        "result": json.dumps({
            "tag": "이벤트",
            "summary": f"event {req_id}",
            "urls": [],
            "event_period": {"start": "2026-04-17", "end": "2026-04-17"},
        }, ensure_ascii=False),
    }, ensure_ascii=False)

    post = InstagramPost(
        id=post_id,
        post_id=f"p{post_id}",
        account="test_account",
        url=f"https://instagram.com/p/{post_id}",
        caption="caption",
        images=[],
    )
    request = LLMRequest(
        id=req_id,
        caller_type="instagram",
        caller_id=str(post_id),
        prompt="test",
        status="completed",
        request_source="instagram_event",
        result=payload_json,
        processed_at=processed_at,
    )
    session.add_all([post, request])
    session.commit()
    return post, request


def test_date_range_since_filters_out_earlier_requests():
    """--since 2026-04-15 시 이전 날짜(4/14) request는 후보에서 제외된다."""
    session, engine = _make_full_session()
    try:
        _make_request_with_processed_at(session, 10001, 50001, datetime(2026, 4, 14, 10, 0, 0))
        _make_request_with_processed_at(session, 10002, 50002, datetime(2026, 4, 15, 10, 0, 0))

        args = argparse.Namespace(
            request_id=None,
            limit=100,
            request_source=None,
            since="2026-04-15",
            until=None,
        )
        candidates = m.load_candidates(session, args)
        candidate_req_ids = [c.request_id for c in candidates]

        assert 10001 not in candidate_req_ids, "4/14 request는 --since 2026-04-15 이후에서 제외돼야 한다"
        assert 10002 in candidate_req_ids, "4/15 request는 --since 2026-04-15 범위에 포함돼야 한다"
    finally:
        session.close()
        engine.dispose()


def test_date_range_until_filters_out_later_requests():
    """--until 2026-04-15 시 이후 날짜(4/16) request는 후보에서 제외된다."""
    session, engine = _make_full_session()
    try:
        _make_request_with_processed_at(session, 10003, 50003, datetime(2026, 4, 15, 10, 0, 0))
        _make_request_with_processed_at(session, 10004, 50004, datetime(2026, 4, 16, 10, 0, 0))

        args = argparse.Namespace(
            request_id=None,
            limit=100,
            request_source=None,
            since=None,
            until="2026-04-15",
        )
        candidates = m.load_candidates(session, args)
        candidate_req_ids = [c.request_id for c in candidates]

        assert 10003 in candidate_req_ids, "4/15 request는 --until 2026-04-15 범위에 포함돼야 한다"
        assert 10004 not in candidate_req_ids, "4/16 request는 --until 2026-04-15 이후에서 제외돼야 한다"
    finally:
        session.close()
        engine.dispose()


def test_date_range_since_until_combined():
    """--since 2026-04-14 --until 2026-04-16 시 해당 범위만 포함된다."""
    session, engine = _make_full_session()
    try:
        _make_request_with_processed_at(session, 10005, 50005, datetime(2026, 4, 13, 23, 59, 0))
        _make_request_with_processed_at(session, 10006, 50006, datetime(2026, 4, 14, 0, 1, 0))
        _make_request_with_processed_at(session, 10007, 50007, datetime(2026, 4, 16, 22, 0, 0))
        _make_request_with_processed_at(session, 10008, 50008, datetime(2026, 4, 17, 0, 1, 0))

        args = argparse.Namespace(
            request_id=None,
            limit=100,
            request_source=None,
            since="2026-04-14",
            until="2026-04-16",
        )
        candidates = m.load_candidates(session, args)
        candidate_req_ids = [c.request_id for c in candidates]

        assert 10005 not in candidate_req_ids, "4/13 request는 범위 밖이므로 제외"
        assert 10006 in candidate_req_ids, "4/14 request는 범위 내"
        assert 10007 in candidate_req_ids, "4/16 request는 범위 내"
        assert 10008 not in candidate_req_ids, "4/17 request는 범위 밖이므로 제외"
    finally:
        session.close()
        engine.dispose()


def test_dry_run_summary_output_format(capsys):
    """print_candidates가 summary 행(create/relink/skip 집계)을 출력한다."""
    candidates = [
        m.Candidate(
            request_id=i, post_id=i, request_source=None, processed_at=None,
            account="a", summary="s", organizer=None, event_start=None,
            event_end=None, event_url=None, existing_event_id=None,
            classified_type=None, classified_id=None, action=action, reason="r",
            payload={"tag": "이벤트"},
        )
        for i, action in enumerate(["create", "create", "relink", "repair", "requeue", "skip"])
    ]
    m.print_candidates(candidates)
    captured = capsys.readouterr()
    assert "summary create=2 relink=1 repair=1 requeue=1 skip=1" in captured.out


def test_existing_regression_create_still_passes():
    """기존 create/relink/duplicate_url 회귀 TC가 날짜 범위 옵션 추가 후에도 동작한다."""
    session, engine = _make_full_session()
    try:
        post = InstagramPost(id=600, post_id="p600", account="acc", caption="c")
        session.add(post)
        session.commit()

        candidate = m.Candidate(
            request_id=999, post_id=600, request_source="instagram_event",
            processed_at=datetime(2026, 4, 14), account="acc",
            summary="테스트", organizer=None, event_start=None, event_end=None,
            event_url=None, existing_event_id=None, classified_type=None, classified_id=None,
            action="create", reason="missing_event_row",
            payload={
                "tag": "이벤트", "summary": "테스트", "urls": [],
                "event_period": {"start": "2026-04-17", "end": "2026-04-17"},
            },
        )
        outcome = m.recover_candidate(session, candidate)
        assert outcome.changed is True
        assert outcome.action == "create"
    finally:
        session.close()
        engine.dispose()

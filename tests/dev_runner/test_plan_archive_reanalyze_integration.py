"""Phase 4-G: manual reanalyze integration tests.

manual reanalyze 흐름(analysis-reanalyze, manual:reanalyze trigger source, model override) 후
audit snapshot(plan_archive_analysis_overwritten)이 PlanEvent에 기록되는지 검증한다.
또한 실패 시 기존 PlanRecord 결과가 유지되고 audit snapshot이 조회 가능한지 검증한다.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.plan_record import PlanEvent, PlanRecord


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _add_analyzed_record(db, **kwargs) -> PlanRecord:
    record = PlanRecord(
        filename_hash=kwargs.pop("filename_hash", "reanalyze-hash-001"),
        file_path=kwargs.pop("file_path", "docs/archive/2026-05-06_reanalyze-test.md"),
        archived_at=kwargs.pop("archived_at", datetime.now()),
        status=kwargs.pop("status", "archived"),
        category=kwargs.pop("category", "infra"),
        summary=kwargs.pop("summary", "original summary"),
        tags=kwargs.pop("tags", ["feat"]),
        llm_processed_at=kwargs.pop("llm_processed_at", datetime.now()),
        raw_content=kwargs.pop("raw_content", "# reanalyze test\n\nbody"),
        **kwargs,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _make_mock_request(record: PlanRecord, *, source: str = "manual:reanalyze", provider: str = "codex", model: str = "gpt-5.5"):
    req = MagicMock()
    req.caller_id = str(record.id)
    req.caller_type = "plan_archive_analyze"
    req.request_source = source
    req.provider = provider
    req.model = model
    req.id = 42
    req.cli_options = '{"profile_key": null}'
    return req


def test_save_plan_archive_result_records_overwritten_audit_snapshot(db):
    """manual:reanalyze 흐름 후 plan_archive_analysis_overwritten 이벤트가 PlanEvent에 기록된다."""
    from app.modules.claude_worker.services.plan_analyze_handler import save_plan_archive_result

    record = _add_analyzed_record(db, category="infra", summary="old summary")
    request = _make_mock_request(record, source="manual:reanalyze", provider="codex", model="gpt-5.5")

    result = {
        "success": True,
        "result": {
            "category": "refactor",
            "tags": ["fix"],
            "summary": "new summary after reanalyze",
            "intent": "fix",
            "trigger": "regression",
            "scope": ["backend"],
        },
        "raw_response": '{"category":"refactor"}',
    }

    with patch(
        "app.modules.dev_runner.services.plan_archive_relation_service.PlanArchiveRelationService"
    ):
        save_plan_archive_result(db, request, result)

    db.refresh(record)
    assert record.category == "refactor"
    assert record.summary == "new summary after reanalyze"

    events = (
        db.query(PlanEvent)
        .filter_by(plan_record_id=record.id, event_type="plan_archive_analysis_overwritten")
        .all()
    )
    assert len(events) == 1
    snapshot = events[0].detail
    assert snapshot["prior_category"] == "infra"
    assert snapshot["prior_summary"] == "old summary"
    assert snapshot["provider"] == "codex"
    assert snapshot["model"] == "gpt-5.5"


def test_save_plan_archive_result_overwritten_event_includes_null_prior_analyzed_at(db):
    """최초 분석(llm_processed_at=None) 상태에서도 manual:reanalyze 소스면 overwritten 이벤트가 생성되고
    prior_analyzed_at이 None으로 기록된다."""
    from app.modules.claude_worker.services.plan_analyze_handler import save_plan_archive_result

    record = _add_analyzed_record(
        db,
        category=None,
        summary=None,
        tags=None,
        llm_processed_at=None,
        filename_hash="reanalyze-hash-002",
    )
    request = _make_mock_request(record, source="manual:reanalyze")

    result = {
        "success": True,
        "result": {
            "category": "feat",
            "tags": ["feat"],
            "summary": "first analysis",
            "intent": "build",
        },
        "raw_response": '{"category":"feat"}',
    }

    with patch(
        "app.modules.dev_runner.services.plan_archive_relation_service.PlanArchiveRelationService"
    ):
        save_plan_archive_result(db, request, result)

    overwritten_events = (
        db.query(PlanEvent)
        .filter_by(plan_record_id=record.id, event_type="plan_archive_analysis_overwritten")
        .all()
    )
    assert len(overwritten_events) == 1
    assert overwritten_events[0].detail["prior_analyzed_at"] is None

    saved_events = (
        db.query(PlanEvent)
        .filter_by(plan_record_id=record.id, event_type="plan_archive_analysis_saved")
        .all()
    )
    assert len(saved_events) == 1


def test_save_plan_archive_result_preserves_record_on_failure(db):
    """LLM 결과 저장 실패 시 기존 PlanRecord의 category/summary가 유지된다."""
    from app.modules.claude_worker.services.plan_analyze_handler import save_plan_archive_result

    record = _add_analyzed_record(
        db,
        category="docs",
        summary="preserved summary",
        filename_hash="reanalyze-hash-003",
    )
    original_category = record.category
    original_summary = record.summary

    request = _make_mock_request(record, source="manual:reanalyze")

    with patch(
        "app.modules.claude_worker.services.plan_analyze_handler._has_newer_plan_archive_result",
        return_value=True,
    ):
        result = save_plan_archive_result(
            db,
            request,
            {"success": True, "result": {"category": "overridden"}, "raw_response": ""},
        )

    assert result is False
    db.refresh(record)
    assert record.category == original_category
    assert record.summary == original_summary


def test_overwritten_audit_snapshot_is_queryable(db):
    """plan_archive_analysis_overwritten audit snapshot이 PlanEvent에서 detail 조회 가능하다."""
    from app.modules.claude_worker.services.plan_analyze_handler import save_plan_archive_result

    record = _add_analyzed_record(
        db,
        category="infra",
        summary="before reanalyze",
        filename_hash="reanalyze-hash-004",
    )
    request = _make_mock_request(record, source="manual:reanalyze", provider="gemini", model="gemini-2.5-pro")

    result = {
        "success": True,
        "result": {"category": "security", "tags": ["fix"], "summary": "after reanalyze"},
        "raw_response": '{"category":"security"}',
    }

    with patch(
        "app.modules.dev_runner.services.plan_archive_relation_service.PlanArchiveRelationService"
    ):
        save_plan_archive_result(db, request, result)

    event = (
        db.query(PlanEvent)
        .filter_by(plan_record_id=record.id, event_type="plan_archive_analysis_overwritten")
        .first()
    )
    assert event is not None
    assert event.detail is not None
    assert event.detail["prior_category"] == "infra"
    assert event.detail["provider"] == "gemini"
    assert event.detail["model"] == "gemini-2.5-pro"
    assert event.detail["request_id"] == 42

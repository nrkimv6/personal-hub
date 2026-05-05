from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_archive_insight import PlanArchiveInsightReport
from app.models.plan_record import PlanRecord, PlanRecordChunk, PlanRecordFileRef, PlanRecordRelation
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.dev_runner.services.plan_archive_insight_service import (
    CALLER_TYPE_PLAN_ARCHIVE_INSIGHT_BATCH,
    PlanArchiveInsightBatchQuery,
    PlanArchiveInsightService,
)


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    for table in (
        PlanRecord.__table__,
        PlanRecordChunk.__table__,
        PlanRecordFileRef.__table__,
        PlanRecordRelation.__table__,
        PlanArchiveInsightReport.__table__,
        LLMRequest.__table__,
    ):
        table.create(bind=engine, checkfirst=True)
    return sessionmaker(bind=engine)(), engine


def _add_archive_record(db):
    record = PlanRecord(
        filename_hash="insight-hash",
        file_path="docs/archive/2026-01-01-insight.md",
        category="infra",
        archived_at=datetime(2026, 1, 1),
        status="archived",
        raw_content="this full raw content must not be in prompt",
    )
    db.add(record)
    db.flush()
    db.add(
        PlanRecordChunk(
            plan_record_id=record.id,
            chunk_index=0,
            section_type="body",
            heading="Queue",
            text="insight evidence from metrics context",
            content_hash="hash",
            token_estimate=5,
        )
    )
    db.add(
        PlanRecordFileRef(
            plan_record_id=record.id,
            source_type="mentioned_in_plan",
            path="app/service.py",
            module="app",
        )
    )
    db.commit()
    return record


def test_build_prompt_uses_metrics_and_evidence_only_compliance():
    db, engine = _make_session()
    try:
        _add_archive_record(db)
        svc = PlanArchiveInsightService(db)
        result = svc.preview_or_enqueue(
            PlanArchiveInsightBatchQuery(category="infra", limit=5),
            provider="claude",
            model="sonnet",
        )
        assert result["dry_run"] is True
        assert result["metrics"]["total_plans"] == 1
        assert result["evidence"]
        assert "this full raw content must not be in prompt" not in result["prompt"]
    finally:
        db.close()
        engine.dispose()


def test_build_prompt_boundary_token_budget_samples_evidence():
    db, engine = _make_session()
    try:
        _add_archive_record(db)
        result = PlanArchiveInsightService(db).preview_or_enqueue(
            PlanArchiveInsightBatchQuery(category="infra", token_budget=200),
            provider="claude",
            model="sonnet",
        )
        assert result["evidence"]
        assert result["warnings"] == []
    finally:
        db.close()
        engine.dispose()


def test_dry_run_does_not_create_llm_request_right():
    db, engine = _make_session()
    try:
        _add_archive_record(db)
        result = PlanArchiveInsightService(db).preview_or_enqueue(
            PlanArchiveInsightBatchQuery(category="infra"),
            provider="claude",
            model="sonnet",
        )
        assert result["queued"] is False
        assert db.query(LLMRequest).count() == 0
        assert db.query(PlanArchiveInsightReport).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_apply_creates_llm_request_right():
    db, engine = _make_session()
    try:
        _add_archive_record(db)
        result = PlanArchiveInsightService(db).preview_or_enqueue(
            PlanArchiveInsightBatchQuery(category="infra"),
            apply=True,
            provider="claude",
            model="sonnet",
        )
        assert result["queued"] is True
        report = db.query(PlanArchiveInsightReport).one()
        request = db.query(LLMRequest).one()
        assert report.llm_request_id == request.id
        assert request.caller_type == CALLER_TYPE_PLAN_ARCHIVE_INSIGHT_BATCH
        assert request.caller_id == str(report.id)
    finally:
        db.close()
        engine.dispose()


def test_apply_error_duplicate_active_request_is_rejected_or_skipped():
    db, engine = _make_session()
    try:
        _add_archive_record(db)
        query = PlanArchiveInsightBatchQuery(category="infra")
        first = PlanArchiveInsightService(db).preview_or_enqueue(
            query,
            apply=True,
            provider="claude",
            model="sonnet",
        )
        second = PlanArchiveInsightService(db).preview_or_enqueue(
            query,
            apply=True,
            provider="claude",
            model="sonnet",
        )
        assert first["queued"] is True
        assert second["skipped"] is True
        assert second["reason"] == "DUPLICATE_ACTIVE_REQUEST"
        assert db.query(LLMRequest).count() == 1
    finally:
        db.close()
        engine.dispose()

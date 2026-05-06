from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_archive_insight import PlanArchiveInsightReport
from app.models.plan_record import PlanRecord, PlanRecordChunk, PlanRecordFileRef, PlanRecordRelation
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.dev_runner.services.plan_archive_insight_service import (
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


def _seed(db):
    record = PlanRecord(
        filename_hash="integration",
        file_path="docs/archive/2026-01-01-integration.md",
        category="infra",
        archived_at=datetime(2026, 1, 1),
        status="archived",
        raw_content="raw plan body must stay out",
    )
    db.add(record)
    db.flush()
    db.add(
        PlanRecordChunk(
            plan_record_id=record.id,
            chunk_index=0,
            section_type="body",
            text="duplicate active request evidence",
            content_hash="h",
            token_estimate=4,
        )
    )
    db.add(PlanRecordFileRef(plan_record_id=record.id, source_type="git_changed", path="app/a.py", module="app"))
    db.commit()


def test_metrics_context_fixture_creates_report_queue():
    db, engine = _make_session()
    try:
        _seed(db)
        result = PlanArchiveInsightService(db).preview_or_enqueue(
            PlanArchiveInsightBatchQuery(category="infra"),
            apply=True,
            provider="claude",
            model="sonnet",
        )
        assert result["queued"] is True
        assert db.query(PlanArchiveInsightReport).count() == 1
        assert db.query(LLMRequest).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_raw_content_full_body_not_in_prompt():
    db, engine = _make_session()
    try:
        _seed(db)
        result = PlanArchiveInsightService(db).preview_or_enqueue(
            PlanArchiveInsightBatchQuery(category="infra"),
            provider="claude",
            model="sonnet",
        )
        assert "raw plan body must stay out" not in result["prompt"]
        assert "duplicate active request evidence" in result["prompt"]
    finally:
        db.close()
        engine.dispose()


def test_duplicate_active_request_skips():
    db, engine = _make_session()
    try:
        _seed(db)
        query = PlanArchiveInsightBatchQuery(category="infra")
        PlanArchiveInsightService(db).preview_or_enqueue(query, apply=True, provider="claude", model="sonnet")
        result = PlanArchiveInsightService(db).preview_or_enqueue(query, apply=True, provider="claude", model="sonnet")
        assert result["skipped"] is True
        assert result["reason"] == "DUPLICATE_ACTIVE_REQUEST"
    finally:
        db.close()
        engine.dispose()

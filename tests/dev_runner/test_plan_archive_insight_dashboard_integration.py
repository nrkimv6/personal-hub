from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_archive_insight import PlanArchiveInsightReport
from app.models.plan_record import PlanRecord, PlanRecordChunk, PlanRecordFileRef
from app.modules.dev_runner.services.plan_archive_insight_review_service import PlanArchiveInsightReviewService


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    for table in (
        PlanRecord.__table__,
        PlanRecordChunk.__table__,
        PlanRecordFileRef.__table__,
        PlanArchiveInsightReport.__table__,
    ):
        table.create(bind=engine, checkfirst=True)
    return sessionmaker(bind=engine)(), engine


def _seed(db):
    record = PlanRecord(
        filename_hash="hash",
        file_path="docs/archive/a.md",
        archived_at=datetime(2026, 1, 1),
        status="archived",
    )
    db.add(record)
    db.flush()
    chunk = PlanRecordChunk(
        plan_record_id=record.id,
        chunk_index=0,
        section_type="body",
        text="chunk evidence",
        content_hash="h",
        token_estimate=2,
    )
    db.add(chunk)
    db.flush()
    report = PlanArchiveInsightReport(
        grouping="category",
        metrics_hash="hash",
        metrics_json={"total_plans": 1},
        evidence_json=[{"record_id": record.id, "chunk_id": chunk.id}],
        insight_json={
            "summary": "summary",
            "suggested_plan_candidates": [{"title": "Candidate", "reason": "reason", "evidence_ids": ["chunk:1"]}],
        },
        provider="claude",
        model="sonnet",
        status="completed",
    )
    db.add(report)
    db.commit()
    return report, chunk


def test_report_detail_evidence_chunk_is_resolved():
    db, engine = _make_session()
    try:
        report, chunk = _seed(db)
        result = PlanArchiveInsightReviewService(db).get_evidence_source(report.id, "chunk", chunk.id)
        assert result["chunk"]["text"] == "chunk evidence"
    finally:
        db.close()
        engine.dispose()


def test_promote_plan_creates_draft_in_plans_worktree(tmp_path):
    db, engine = _make_session()
    try:
        report, _chunk = _seed(db)
        result = PlanArchiveInsightReviewService(db, plans_dir=tmp_path).promote_plan_candidate(report.id, 0, confirm=True)
        assert result["path"].endswith(".md")
        assert next(tmp_path.glob("*.md")).exists()
    finally:
        db.close()
        engine.dispose()


def test_missing_source_recommendation_returns_warning(tmp_path):
    db, engine = _make_session()
    try:
        report, _chunk = _seed(db)
        report.insight_json = {"suggested_plan_candidates": [{"title": "No source", "reason": "reason"}]}
        db.commit()
        PlanArchiveInsightReviewService(db, plans_dir=tmp_path).promote_plan_candidate(report.id, 0, confirm=True)
        assert "source 없음" in next(tmp_path.glob("*.md")).read_text(encoding="utf-8")
    finally:
        db.close()
        engine.dispose()

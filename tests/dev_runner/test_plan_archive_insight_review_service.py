from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_archive_insight import PlanArchiveInsightReport
from app.modules.dev_runner.services.plan_archive_insight_review_service import PlanArchiveInsightReviewService


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    PlanArchiveInsightReport.__table__.create(bind=engine, checkfirst=True)
    return sessionmaker(bind=engine)(), engine


def _add_report(db):
    report = PlanArchiveInsightReport(
        range_start=datetime(2026, 1, 1),
        range_end=datetime(2026, 1, 31),
        grouping="category",
        metrics_hash="hash",
        metrics_json={"total_plans": 1},
        evidence_json=[{"record_id": 1, "chunk_id": 1, "text": "evidence"}],
        insight_json={
            "summary": "summary",
            "root_causes": ["root"],
            "recommendations": ["recommend"],
            "suggested_plan_candidates": [
                {"title": "Follow up", "reason": "reason", "evidence_ids": ["record:1"]}
            ],
        },
        provider="claude",
        model="sonnet",
        status="completed",
    )
    db.add(report)
    db.commit()
    return report


def test_update_review_status_right():
    db, engine = _make_session()
    try:
        report = _add_report(db)
        result = PlanArchiveInsightReviewService(db).update_review(report.id, "reviewing", "checking")
        assert result["review_status"] == "reviewing"
        assert result["review_note"] == "checking"
    finally:
        db.close()
        engine.dispose()


def test_update_review_status_error_invalid_transition():
    db, engine = _make_session()
    try:
        report = _add_report(db)
        PlanArchiveInsightReviewService(db).update_review(report.id, "rejected")
        with pytest.raises(ValueError, match="INVALID_REVIEW_TRANSITION"):
            PlanArchiveInsightReviewService(db).update_review(report.id, "promoted")
    finally:
        db.close()
        engine.dispose()


def test_promote_plan_candidate_creates_plan_draft_right(tmp_path):
    db, engine = _make_session()
    try:
        report = _add_report(db)
        result = PlanArchiveInsightReviewService(db, plans_dir=tmp_path).promote_plan_candidate(
            report.id,
            0,
            confirm=True,
        )
        path = tmp_path / result["path"].split("\\")[-1]
        assert path.exists()
        assert result["report"]["review_status"] == "promoted"
    finally:
        db.close()
        engine.dispose()


def test_promote_plan_candidate_boundary_missing_evidence_requires_warning(tmp_path):
    db, engine = _make_session()
    try:
        report = _add_report(db)
        report.insight_json = {"suggested_plan_candidates": [{"title": "No evidence", "reason": "reason"}]}
        db.commit()
        result = PlanArchiveInsightReviewService(db, plans_dir=tmp_path).promote_plan_candidate(
            report.id,
            0,
            confirm=True,
        )
        content = next(tmp_path.glob("*.md")).read_text(encoding="utf-8")
        assert "source 없음" in content
        assert result["path"]
    finally:
        db.close()
        engine.dispose()

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_archive_insight import PlanArchiveInsightReport


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    PlanArchiveInsightReport.__table__.create(bind=engine, checkfirst=True)
    return sessionmaker(bind=engine)(), engine


def test_insight_report_tables_exist_right():
    db, engine = _make_session()
    try:
        report = PlanArchiveInsightReport(
            range_start=datetime(2026, 1, 1),
            range_end=datetime(2026, 1, 31),
            grouping="category",
            metrics_hash="hash",
            metrics_json={"total_plans": 1},
            evidence_json=[{"record_id": 1}],
            provider="claude",
            model="sonnet",
        )
        db.add(report)
        db.commit()
        assert report.id is not None
    finally:
        db.close()
        engine.dispose()


def test_insight_report_boundary_empty_evidence_is_allowed_with_warning():
    db, engine = _make_session()
    try:
        report = PlanArchiveInsightReport(
            grouping="module",
            metrics_hash="empty",
            metrics_json={"total_plans": 0},
            evidence_json=[],
            provider="claude",
            model="sonnet",
            warning="EMPTY_EVIDENCE",
        )
        db.add(report)
        db.commit()
        saved = db.query(PlanArchiveInsightReport).one()
        assert saved.evidence_json == []
        assert saved.warning == "EMPTY_EVIDENCE"
    finally:
        db.close()
        engine.dispose()

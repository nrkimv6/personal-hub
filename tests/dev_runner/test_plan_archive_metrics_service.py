from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanRecord, PlanRecordFileRef, PlanRecordRelation
from app.modules.dev_runner.services.plan_archive_metrics_service import PlanArchiveMetricsService
from app.modules.dev_runner.services.plan_archive_retrieval_service import RetrievalQuery


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    for table in (
        PlanRecord.__table__,
        PlanRecordFileRef.__table__,
        PlanRecordRelation.__table__,
    ):
        table.create(bind=engine, checkfirst=True)
    return sessionmaker(bind=engine)(), engine


def test_followup_rate_7_14_30_days_right():
    db, engine = _make_session()
    try:
        first = PlanRecord(
            filename_hash="hash-m1",
            file_path="docs/archive/2026-01-01-a.md",
            category="infra",
            archived_at=datetime(2026, 1, 1),
            status="archived",
            recurrence_count=1,
        )
        second = PlanRecord(
            filename_hash="hash-m2",
            file_path="docs/archive/2026-01-05-b.md",
            category="infra",
            archived_at=datetime(2026, 1, 5),
            status="archived",
            recurrence_count=2,
        )
        db.add_all([first, second])
        db.flush()
        db.add_all(
            [
                PlanRecordFileRef(plan_record_id=first.id, source_type="git_changed", path="app/a.py", module="app"),
                PlanRecordFileRef(plan_record_id=second.id, source_type="git_changed", path="app/b.py", module="app"),
                PlanRecordRelation(source_plan_record_id=first.id, target_plan_record_id=second.id, relation_type="follow_up"),
            ]
        )
        db.flush()
        result = PlanArchiveMetricsService(db).calculate(RetrievalQuery(category="infra"))
        assert result["followup_rates"]["days_7"] > 0
        assert result["chain_depth_max"] == 2
        assert result["relation_counts"]["follow_up"] == 1
    finally:
        db.close()
        engine.dispose()

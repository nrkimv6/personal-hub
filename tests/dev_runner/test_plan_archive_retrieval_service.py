from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanRecord, PlanRecordChunk, PlanRecordFileRef, PlanRecordRelation
from app.modules.dev_runner.services.plan_archive_retrieval_service import PlanArchiveRetrievalService, RetrievalQuery


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    for table in (
        PlanRecord.__table__,
        PlanRecordChunk.__table__,
        PlanRecordFileRef.__table__,
        PlanRecordRelation.__table__,
    ):
        table.create(bind=engine, checkfirst=True)
    return sessionmaker(bind=engine)(), engine


def test_retrieval_metadata_then_lexical_ranking_right():
    db, engine = _make_session()
    try:
        record = PlanRecord(
            filename_hash="hash-r",
            file_path="docs/archive/2026-01-01-r.md",
            title="Retrieval",
            category="infra",
            archived_at=datetime.now(),
            status="archived",
        )
        db.add(record)
        db.flush()
        db.add(
            PlanRecordChunk(
                plan_record_id=record.id,
                chunk_index=0,
                section_type="section",
                heading="Overview",
                text="lexical retrieval evidence",
                content_hash="h",
                token_estimate=3,
            )
        )
        db.flush()
        result = PlanArchiveRetrievalService(db).search(RetrievalQuery(q="retrieval", category="infra"))
        assert result["total"] == 1
        assert result["results"][0]["chunks"][0]["snippet"]
    finally:
        db.close()
        engine.dispose()


def test_retrieval_file_path_scores_mentioned_and_changed_reference():
    db, engine = _make_session()
    try:
        record = PlanRecord(
            filename_hash="hash-f",
            file_path="docs/archive/2026-01-01-f.md",
            archived_at=datetime.now(),
            status="archived",
        )
        db.add(record)
        db.flush()
        db.add_all(
            [
                PlanRecordFileRef(
                    plan_record_id=record.id,
                    source_type="mentioned_in_plan",
                    path="app/models/plan_record.py",
                    module="app/models",
                ),
                PlanRecordFileRef(
                    plan_record_id=record.id,
                    source_type="git_changed",
                    path="app/models/plan_record.py",
                    module="app/models",
                    commit_sha="abc",
                ),
            ]
        )
        db.flush()
        result = PlanArchiveRetrievalService(db).search(RetrievalQuery(path="plan_record.py"))
        assert result["total"] == 1
        assert {ref["source_type"] for ref in result["results"][0]["file_refs"]} == {"mentioned_in_plan", "git_changed"}
    finally:
        db.close()
        engine.dispose()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import (
    PlanRecord,
    PlanRecordChunk,
    PlanRecordFileRef,
    PlanRecordRelation,
    PlanRecordSearchRun,
)


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    for table in (
        PlanRecord.__table__,
        PlanRecordChunk.__table__,
        PlanRecordFileRef.__table__,
        PlanRecordRelation.__table__,
        PlanRecordSearchRun.__table__,
    ):
        table.create(bind=engine, checkfirst=True)
    return sessionmaker(bind=engine)(), engine


def test_retrieval_tables_exist_right():
    db, engine = _make_session()
    try:
        names = set(engine.dialect.get_table_names(engine.connect()))
        assert "plan_record_chunks" in names
        assert "plan_record_file_refs" in names
        assert "plan_record_relations" in names
        assert "plan_record_search_runs" in names
    finally:
        db.close()
        engine.dispose()


def test_plan_record_chunk_relationship_right():
    db, engine = _make_session()
    try:
        record = PlanRecord(filename_hash="hash1", file_path="docs/archive/2026-01-01-a.md")
        db.add(record)
        db.flush()
        db.add(
            PlanRecordChunk(
                plan_record_id=record.id,
                chunk_index=0,
                section_type="todo",
                text="- [ ] app/models/plan_record.py",
                content_hash="h",
                token_estimate=3,
            )
        )
        db.flush()
        assert record.chunks[0].section_type == "todo"
    finally:
        db.close()
        engine.dispose()


def test_file_ref_unique_key_boundary():
    db, engine = _make_session()
    try:
        record = PlanRecord(filename_hash="hash2", file_path="docs/archive/2026-01-01-b.md")
        db.add(record)
        db.flush()
        db.add(
            PlanRecordFileRef(
                plan_record_id=record.id,
                source_type="git_changed",
                path="app/models/plan_record.py",
                commit_sha="abc",
            )
        )
        db.flush()
        db.add(
            PlanRecordFileRef(
                plan_record_id=record.id,
                source_type="git_changed",
                path="app/models/plan_record.py",
                commit_sha="def",
            )
        )
        db.flush()
        assert db.query(PlanRecordFileRef).count() == 2
    finally:
        db.close()
        engine.dispose()


def test_search_run_records_error_state_error():
    db, engine = _make_session()
    try:
        run = PlanRecordSearchRun(status="failed", error_message="boom", failed_count=1)
        db.add(run)
        db.flush()
        assert db.query(PlanRecordSearchRun).first().error_message == "boom"
    finally:
        db.close()
        engine.dispose()

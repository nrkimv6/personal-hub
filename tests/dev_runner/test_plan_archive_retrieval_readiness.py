"""Plan Archive retrieval DB readiness contracts."""

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.plan_record import (
    PlanRecord,
    PlanRecordChunk,
    PlanRecordFileRef,
    PlanRecordRelation,
    PlanRecordSearchRun,
)
from app.modules.dev_runner.services.plan_archive_retrieval_readiness import (
    check_plan_archive_retrieval_tables,
    get_plan_archive_retrieval_readiness,
)


def _session_with_tables(tables):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in tables:
        table.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()
    return engine, session


def test_plan_archive_retrieval_tables_right_all_present():
    engine, session = _session_with_tables([
        PlanRecord.__table__,
        PlanRecordChunk.__table__,
        PlanRecordFileRef.__table__,
        PlanRecordRelation.__table__,
        PlanRecordSearchRun.__table__,
    ])
    try:
        assert check_plan_archive_retrieval_tables(session) == []
        readiness = get_plan_archive_retrieval_readiness(session)
        assert readiness["ok"] is True
        assert readiness["missing_tables"] == []
    finally:
        session.close()
        engine.dispose()


def test_plan_archive_retrieval_tables_error_missing_file_refs():
    engine, session = _session_with_tables([
        PlanRecord.__table__,
        PlanRecordChunk.__table__,
        PlanRecordRelation.__table__,
        PlanRecordSearchRun.__table__,
    ])
    try:
        missing = check_plan_archive_retrieval_tables(session)
        assert "plan_record_file_refs" in missing
        readiness = get_plan_archive_retrieval_readiness(session)
        assert readiness["ok"] is False
        assert readiness["missing_tables"] == ["plan_record_file_refs"]
    finally:
        session.close()
        engine.dispose()


def test_plan_archive_retrieval_tables_right_does_not_create_schema():
    engine, session = _session_with_tables([])
    try:
        missing = check_plan_archive_retrieval_tables(session)

        assert sorted(missing) == sorted([
            "plan_record_chunks",
            "plan_record_file_refs",
            "plan_record_relations",
            "plan_record_search_runs",
        ])
        assert inspect(engine).get_table_names() == []
    finally:
        session.close()
        engine.dispose()

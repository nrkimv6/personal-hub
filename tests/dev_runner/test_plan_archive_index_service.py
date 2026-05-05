from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanRecord, PlanRecordChunk, PlanRecordFileRef, PlanRecordSearchRun
from app.modules.dev_runner.services.plan_archive_file_ref_service import extract_file_refs
from app.modules.dev_runner.services.plan_archive_index_service import PlanArchiveIndexService, split_plan_into_chunks


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    for table in (
        PlanRecord.__table__,
        PlanRecordChunk.__table__,
        PlanRecordFileRef.__table__,
        PlanRecordSearchRun.__table__,
    ):
        table.create(bind=engine, checkfirst=True)
    return sessionmaker(bind=engine)(), engine


def test_split_plan_into_chunks_right_sections():
    chunks = split_plan_into_chunks("# Title\n\n## TODO\n\n- [ ] `app/models/plan_record.py`: update\n\n## 검증\n\npytest")
    assert [chunk.section_type for chunk in chunks] == ["section", "todo", "validation"]
    assert chunks[1].heading == "TODO"


def test_extract_file_refs_right_markdown_paths(tmp_path):
    target = tmp_path / "app" / "models"
    target.mkdir(parents=True)
    (target / "plan_record.py").write_text("", encoding="utf-8")
    refs = extract_file_refs("- [ ] `app/models/plan_record.py`: update", tmp_path)
    assert refs[0].path == "app/models/plan_record.py"
    assert refs[0].exists_at_index is True


def test_index_record_idempotent_reference(tmp_path):
    db, engine = _make_session()
    try:
        app_dir = tmp_path / "app" / "models"
        app_dir.mkdir(parents=True)
        (app_dir / "plan_record.py").write_text("", encoding="utf-8")
        record = PlanRecord(
            filename_hash="hash-index",
            file_path=str(tmp_path / "archive.md"),
            raw_content="# Plan\n\n- [ ] `app/models/plan_record.py`: update",
            archived_at=datetime.now(),
            status="archived",
        )
        db.add(record)
        db.flush()
        svc = PlanArchiveIndexService(db, tmp_path)
        svc.index_record(record.id)
        svc.index_record(record.id, force=True)
        db.flush()
        assert db.query(PlanRecordChunk).filter_by(plan_record_id=record.id).count() == 1
        assert db.query(PlanRecordFileRef).filter_by(plan_record_id=record.id, source_type="mentioned_in_plan").count() == 1
    finally:
        db.close()
        engine.dispose()


def test_index_record_empty_content_error(tmp_path):
    db, engine = _make_session()
    try:
        record = PlanRecord(filename_hash="hash-empty", file_path=str(tmp_path / "missing.md"), archived_at=datetime.now())
        db.add(record)
        db.flush()
        svc = PlanArchiveIndexService(db, tmp_path)
        try:
            svc.index_record(record.id)
        except ValueError as exc:
            assert "raw_content" in str(exc)
        else:
            raise AssertionError("expected ValueError")
    finally:
        db.close()
        engine.dispose()

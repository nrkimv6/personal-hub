import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_archive_doc_patch import PlanArchiveDocPatchProposal
from app.models.plan_record import PlanRecord
from app.modules.dev_runner.services.plan_archive_doc_patch_service import PlanArchiveDocPatchService


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    PlanRecord.__table__.create(bind=engine, checkfirst=True)
    PlanArchiveDocPatchProposal.__table__.create(bind=engine, checkfirst=True)
    return sessionmaker(bind=engine)(), engine


def test_preview_keeps_real_archive_file_unchanged(tmp_path):
    db, engine = _make_session()
    try:
        archive_dir = tmp_path / "plans" / "docs" / "archive"
        archive_dir.mkdir(parents=True)
        target = archive_dir / "real.md"
        target.write_text("old", encoding="utf-8")
        record = PlanRecord(filename_hash="h1", file_path=str(target), status="archived")
        db.add(record)
        db.commit()
        PlanArchiveDocPatchService(db, archive_dir=archive_dir).preview(
            record_id=record.id,
            patch_text=json.dumps({"replacements": [{"old": "old", "new": "new"}]}),
        )
        assert target.read_text(encoding="utf-8") == "old"
    finally:
        db.close()
        engine.dispose()


def test_apply_records_commit_hash(tmp_path):
    db, engine = _make_session()
    try:
        plans = tmp_path / "plans"
        archive_dir = plans / "docs" / "archive"
        archive_dir.mkdir(parents=True)
        target = archive_dir / "real.md"
        target.write_text("old", encoding="utf-8")
        record = PlanRecord(filename_hash="h2", file_path=str(target), status="archived")
        db.add(record)
        db.commit()
        service = PlanArchiveDocPatchService(
            db,
            archive_dir=archive_dir,
            plans_worktree_dir=plans,
            commit_runner=lambda _path, _message: "commit123",
        )
        proposal = service.preview(
            record_id=record.id,
            patch_text=json.dumps({"replacements": [{"old": "old", "new": "new"}]}),
        )
        result = service.apply(proposal["id"], confirm=True)
        assert result["applied_commit"] == "commit123"
    finally:
        db.close()
        engine.dispose()


def test_outside_path_patch_is_not_applied(tmp_path):
    db, engine = _make_session()
    try:
        archive_dir = tmp_path / "plans" / "docs" / "archive"
        archive_dir.mkdir(parents=True)
        outside = tmp_path / "outside.md"
        outside.write_text("old", encoding="utf-8")
        record = PlanRecord(filename_hash="h3", file_path=str(outside), status="archived")
        db.add(record)
        db.commit()
        try:
            PlanArchiveDocPatchService(db, archive_dir=archive_dir).preview(record_id=record.id, patch_text="")
        except ValueError as exc:
            assert str(exc) == "TARGET_OUTSIDE_ARCHIVE"
        assert outside.read_text(encoding="utf-8") == "old"
    finally:
        db.close()
        engine.dispose()

import json
from pathlib import Path

import pytest
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


def _add_record(db, path: Path, raw_content: str | None = None):
    record = PlanRecord(
        filename_hash=f"hash-{path.name}",
        file_path=str(path),
        status="archived",
        raw_content=raw_content,
    )
    db.add(record)
    db.commit()
    return record


def _patch(old: str, new: str) -> str:
    return json.dumps({"replacements": [{"old": old, "new": new}]})


def test_preview_does_not_modify_file_right(tmp_path):
    db, engine = _make_session()
    try:
        archive_dir = tmp_path / "docs" / "archive"
        archive_dir.mkdir(parents=True)
        target = archive_dir / "a.md"
        target.write_text("old text", encoding="utf-8")
        record = _add_record(db, target)
        result = PlanArchiveDocPatchService(db, archive_dir=archive_dir).preview(
            record_id=record.id,
            patch_text=_patch("old", "new"),
        )
        assert target.read_text(encoding="utf-8") == "old text"
        assert result["preview_text"] == "new text"
        assert result["status"] == "previewed"
    finally:
        db.close()
        engine.dispose()


def test_preview_boundary_empty_patch_returns_noop_summary(tmp_path):
    db, engine = _make_session()
    try:
        archive_dir = tmp_path / "docs" / "archive"
        archive_dir.mkdir(parents=True)
        target = archive_dir / "a.md"
        target.write_text("same", encoding="utf-8")
        record = _add_record(db, target)
        result = PlanArchiveDocPatchService(db, archive_dir=archive_dir).preview(record_id=record.id, patch_text="")
        assert result["preview_text"] == "same"
        assert result["changed_lines_summary"][0]["type"] == "noop"
    finally:
        db.close()
        engine.dispose()


def test_apply_rejects_path_outside_archive_compliance(tmp_path):
    db, engine = _make_session()
    try:
        archive_dir = tmp_path / "docs" / "archive"
        archive_dir.mkdir(parents=True)
        outside = tmp_path / "outside.md"
        outside.write_text("old", encoding="utf-8")
        record = _add_record(db, outside)
        with pytest.raises(ValueError, match="TARGET_OUTSIDE_ARCHIVE"):
            PlanArchiveDocPatchService(db, archive_dir=archive_dir).preview(record_id=record.id, patch_text=_patch("old", "new"))
    finally:
        db.close()
        engine.dispose()


def test_apply_success_records_commit_right(tmp_path):
    db, engine = _make_session()
    try:
        plans = tmp_path / "plans"
        archive_dir = plans / "docs" / "archive"
        archive_dir.mkdir(parents=True)
        target = archive_dir / "a.md"
        target.write_text("old", encoding="utf-8")
        record = _add_record(db, target)

        def fake_commit(path, message):
            assert path == target
            assert "doc patch" in message
            return "abc123"

        service = PlanArchiveDocPatchService(db, archive_dir=archive_dir, plans_worktree_dir=plans, commit_runner=fake_commit)
        proposal = service.preview(record_id=record.id, patch_text=_patch("old", "new"))
        result = service.apply(proposal["id"], confirm=True)
        assert target.read_text(encoding="utf-8") == "new"
        assert result["applied_commit"] == "abc123"
        assert result["status"] == "applied"
    finally:
        db.close()
        engine.dispose()


def test_apply_error_malformed_diff_preserves_file(tmp_path):
    db, engine = _make_session()
    try:
        archive_dir = tmp_path / "docs" / "archive"
        archive_dir.mkdir(parents=True)
        target = archive_dir / "a.md"
        target.write_text("old", encoding="utf-8")
        record = _add_record(db, target)
        proposal = PlanArchiveDocPatchProposal(
            plan_record_id=record.id,
            status="previewed",
            target_path=str(target),
            patch_text="{bad json",
        )
        db.add(proposal)
        db.commit()
        with pytest.raises(ValueError, match="MALFORMED_PATCH"):
            PlanArchiveDocPatchService(db, archive_dir=archive_dir).apply(proposal.id, confirm=True)
        assert target.read_text(encoding="utf-8") == "old"
    finally:
        db.close()
        engine.dispose()


def test_patch_failure_preserves_file_error(tmp_path):
    db, engine = _make_session()
    try:
        archive_dir = tmp_path / "docs" / "archive"
        archive_dir.mkdir(parents=True)
        target = archive_dir / "a.md"
        target.write_text("old", encoding="utf-8")
        record = _add_record(db, target)
        service = PlanArchiveDocPatchService(db, archive_dir=archive_dir)
        proposal = service.preview(record_id=record.id, patch_text=_patch("missing", "new"))
        with pytest.raises(ValueError, match="PATCH_TARGET_NOT_FOUND"):
            service.apply(proposal["id"], confirm=True)
        assert target.read_text(encoding="utf-8") == "old"
        saved = db.get(PlanArchiveDocPatchProposal, proposal["id"])
        assert saved.status == "failed"
    finally:
        db.close()
        engine.dispose()

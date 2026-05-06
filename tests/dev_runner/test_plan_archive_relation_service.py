from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanRecord, PlanRecordRelation
from app.modules.dev_runner.services.plan_archive_relation_service import (
    BODY_RELATION_GENERATOR,
    PlanArchiveRelationService,
    classify_plan_relation,
    compute_plan_filename_hash,
    extract_plan_mentions,
)


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    PlanRecord.__table__.create(bind=engine, checkfirst=True)
    PlanRecordRelation.__table__.create(bind=engine, checkfirst=True)
    return sessionmaker(bind=engine)(), engine


def _record(session, filename: str, *, raw_content: str | None = None, file_path: str | None = None) -> PlanRecord:
    record = PlanRecord(
        filename_hash=compute_plan_filename_hash(filename),
        file_path=file_path or f"docs/plan/{filename}",
        title=filename,
        raw_content=raw_content,
        status="planned",
    )
    session.add(record)
    session.flush()
    return record


def test_extract_plan_mentions_right_markdown_links():
    content = "## 선행 계획서\n[remote](../archive/2026-05-06_fix-remote.md) 때문에 후속이 생겼다."

    mentions = extract_plan_mentions(content)

    assert len(mentions) == 1
    assert mentions[0].filename == "2026-05-06_fix-remote.md"
    assert mentions[0].label == "remote"
    assert mentions[0].heading == "선행 계획서"
    assert mentions[0].source == "markdown_link"


def test_extract_plan_mentions_boundary_bare_filename():
    content = "관련: 2026-05-06_fix-root.md, 그리고 path docs/plan/2026-05-06_feat-next.md"

    filenames = {mention.filename for mention in extract_plan_mentions(content)}

    assert filenames == {"2026-05-06_fix-root.md", "2026-05-06_feat-next.md"}


def test_classify_plan_relation_right_predecessor_and_guard():
    mention = extract_plan_mentions(
        "## 선행 계획서\n| 방어 선행 | 2026-05-06_fix-guard.md | 관련 guard 및 재발 방지 |"
    )[0]

    relation_types = classify_plan_relation(mention)

    assert "predecessor" in relation_types
    assert "guard" in relation_types


def test_resolve_target_record_boundary_active_archive_same_filename():
    db, engine = _make_session()
    try:
        target = _record(db, "2026-05-06_fix-target.md", file_path="docs/archive/infra/2026-05-06_fix-target.md")
        db.commit()

        resolved = PlanArchiveRelationService(db).resolve_target_record("docs/plan/2026-05-06_fix-target.md")

        assert resolved.id == target.id
    finally:
        db.close()
        engine.dispose()


def test_refresh_relations_error_skips_ambiguous_target():
    db, engine = _make_session()
    try:
        source = _record(
            db,
            "2026-05-06_fix-source.md",
            raw_content="관련 선행: 2026-05-06_fix-ambiguous.md",
        )
        db.add_all(
            [
                PlanRecord(filename_hash="ambiguous-a", file_path="a/2026-05-06_fix-ambiguous.md"),
                PlanRecord(filename_hash="ambiguous-b", file_path="b/2026-05-06_fix-ambiguous.md"),
            ]
        )
        db.commit()

        result = PlanArchiveRelationService(db).refresh_relations_for_record(source.id)

        assert result.unresolved_targets
        assert db.query(PlanRecordRelation).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_refresh_relations_preserves_existing_semantic_relation():
    db, engine = _make_session()
    try:
        source = _record(db, "2026-05-06_fix-source.md", raw_content="# source\n\nno plan mention")
        target = _record(db, "2026-05-06_fix-target.md")
        db.add(
            PlanRecordRelation(
                source_plan_record_id=source.id,
                target_plan_record_id=target.id,
                relation_type="semantic_similar",
                score=88,
                evidence={"semantic_score": 0.88},
            )
        )
        db.commit()

        PlanArchiveRelationService(db).refresh_relations_for_record(source.id)

        semantic = db.query(PlanRecordRelation).filter_by(relation_type="semantic_similar").one()
        assert semantic.score == 88
        assert semantic.evidence == {"semantic_score": 0.88}
    finally:
        db.close()
        engine.dispose()


def test_refresh_relations_deduplicates_repeated_mentions_for_same_relation():
    db, engine = _make_session()
    try:
        source = _record(
            db,
            "2026-05-06_fix-source.md",
            raw_content="\n".join(
                [
                    "직접 선행: 2026-05-06_fix-target.md",
                    "관련 계획: 2026-05-06_fix-target.md",
                    "다시 언급: 2026-05-06_fix-target.md",
                ]
            ),
        )
        target = _record(db, "2026-05-06_fix-target.md")
        db.commit()

        result = PlanArchiveRelationService(db).refresh_relations_for_record(source.id)
        db.commit()

        assert result.created == 2
        assert any(item["reason"] == "duplicate_body_relation" for item in result.skipped)
        assert db.query(PlanRecordRelation).filter_by(source_plan_record_id=source.id).count() == 2
        relation_types = {
            row.relation_type
            for row in db.query(PlanRecordRelation).filter_by(source_plan_record_id=source.id).all()
        }
        assert relation_types == {"mentions", "predecessor"}
        assert target.id
    finally:
        db.close()
        engine.dispose()


def test_fixture_ingest_creates_predecessor_guard_unresolved_followup():
    db, engine = _make_session()
    try:
        fixture_dir = Path(__file__).resolve().parents[1] / "fixtures" / "plan_archive"
        source = _record(
            db,
            "2026-05-06_fix-root-main-staged-sync-recovery.md",
            raw_content=(fixture_dir / "root_main_staged_sync_recovery.md").read_text(encoding="utf-8"),
        )
        remote = _record(db, "2026-05-06_fix-remote-ff-only-skill-sync-recovery.md")
        guard = _record(db, "2026-05-06_fix-block-mirror-direct-edits.md")
        db.commit()

        PlanArchiveRelationService(db).refresh_relations_for_record(source.id)

        rows = db.query(PlanRecordRelation).filter_by(source_plan_record_id=source.id).all()
        by_target = {(row.target_plan_record_id, row.relation_type) for row in rows}
        assert (remote.id, "predecessor") in by_target
        assert (remote.id, "unresolved_followup") in by_target
        assert (guard.id, "guard") in by_target
        assert all(row.evidence.get("generated_by") == BODY_RELATION_GENERATOR for row in rows)
    finally:
        db.close()
        engine.dispose()

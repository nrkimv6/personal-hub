from __future__ import annotations

from pathlib import Path

from app.models.plan_record import PlanRecordRelation
from app.modules.dev_runner.services.plan_archive_relation_service import (
    PlanArchiveRelationService,
    compute_plan_filename_hash,
)
from app.modules.dev_runner.services.plan_record_service import PlanRecordService


def test_raw_content_refresh_creates_relation_real_db_session(test_db_session):
    svc = PlanRecordService(test_db_session)
    target = svc.ingest_single("/repo/docs/archive/2026-05-06_fix-target.md", raw_content="# target")
    source = svc.ingest_single(
        "/repo/docs/archive/2026-05-06_fix-source.md",
        raw_content="선행 계획서: 2026-05-06_fix-target.md",
    )
    test_db_session.commit()

    PlanArchiveRelationService(test_db_session).refresh_relations_for_record(source.id)

    assert (
        test_db_session.query(PlanRecordRelation)
        .filter_by(source_plan_record_id=source.id, target_plan_record_id=target.id, relation_type="predecessor")
        .count()
        == 1
    )


def test_root_recovery_fixture_unresolved_followup_real_db_session(test_db_session):
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures" / "plan_archive"
    svc = PlanRecordService(test_db_session)
    source = svc.ingest_single(
        "/repo/docs/archive/2026-05-06_fix-root-main-staged-sync-recovery.md",
        raw_content=(fixture_dir / "root_main_staged_sync_recovery.md").read_text(encoding="utf-8"),
    )
    target = svc.ingest_single("/repo/docs/archive/2026-05-06_fix-remote-ff-only-skill-sync-recovery.md", raw_content="# target")
    svc.ingest_single("/repo/docs/archive/2026-05-06_fix-block-mirror-direct-edits.md", raw_content="# guard")
    test_db_session.commit()

    PlanArchiveRelationService(test_db_session).refresh_relations_for_record(source.id)

    assert (
        test_db_session.query(PlanRecordRelation)
        .filter_by(source_plan_record_id=source.id, target_plan_record_id=target.id, relation_type="unresolved_followup")
        .count()
        == 1
    )


def test_sync_all_active_plan_relation_is_queryable(test_db_session, tmp_path):
    active_dir = tmp_path / "docs" / "plan"
    active_dir.mkdir(parents=True)
    target_file = active_dir / "2026-05-06_fix-target.md"
    source_file = active_dir / "2026-05-06_fix-source.md"
    target_file.write_text("# target", encoding="utf-8")
    source_file.write_text("직접 선행: 2026-05-06_fix-target.md", encoding="utf-8")

    result = PlanRecordService(test_db_session).sync_all([{"path": str(active_dir), "type": "plan"}])

    assert result["relation_refreshed"] == 2
    assert test_db_session.query(PlanRecordRelation).filter_by(relation_type="predecessor").count() == 1


def test_archive_move_keeps_filename_hash_relation_target(test_db_session):
    svc = PlanRecordService(test_db_session)
    source = svc.ingest_single(
        "/repo/docs/archive/2026-05-06_fix-source.md",
        raw_content="선행: 2026-05-06_fix-target.md",
    )
    target = svc.ingest_single("/repo/docs/plan/2026-05-06_fix-target.md", raw_content="# target")
    target.file_path = "/repo/docs/archive/infra/2026-05-06_fix-target.md"
    test_db_session.commit()

    PlanArchiveRelationService(test_db_session).refresh_relations_for_record(source.id)

    row = test_db_session.query(PlanRecordRelation).filter_by(relation_type="predecessor").one()
    assert row.target_plan_record_id == target.id
    assert target.filename_hash == compute_plan_filename_hash("2026-05-06_fix-target.md")


def test_semantic_relation_and_body_relation_coexist(test_db_session):
    svc = PlanRecordService(test_db_session)
    semantic_target = svc.ingest_single("/repo/docs/archive/2026-05-06_fix-semantic.md", raw_content="# semantic")
    body_target = svc.ingest_single("/repo/docs/archive/2026-05-06_fix-body.md", raw_content="# body")
    source = svc.ingest_single(
        "/repo/docs/archive/2026-05-06_fix-source.md",
        raw_content="관련 선행: 2026-05-06_fix-body.md",
    )
    test_db_session.add(
        PlanRecordRelation(
            source_plan_record_id=source.id,
            target_plan_record_id=semantic_target.id,
            relation_type="semantic_similar",
            score=91,
            evidence={"semantic_score": 0.91},
        )
    )
    test_db_session.commit()

    PlanArchiveRelationService(test_db_session).refresh_relations_for_record(source.id)

    assert test_db_session.query(PlanRecordRelation).filter_by(relation_type="semantic_similar").count() == 1
    assert (
        test_db_session.query(PlanRecordRelation)
        .filter_by(target_plan_record_id=body_target.id, relation_type="predecessor")
        .count()
        == 1
    )

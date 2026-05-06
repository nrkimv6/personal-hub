from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "plan_runner"))

import reindex_plan_relations as reindex  # noqa: E402
from app.models.plan_archive_execution import PlanArchiveExecutionJob  # noqa: E402,F401
from app.models.plan_record import PlanRecord, PlanRecordRelation  # noqa: E402
from app.modules.dev_runner.services.plan_archive_relation_service import compute_plan_filename_hash  # noqa: E402


def _seed(tmp_path):
    db_path = tmp_path / "relations.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    PlanRecord.__table__.create(bind=engine, checkfirst=True)
    PlanRecordRelation.__table__.create(bind=engine, checkfirst=True)
    session = sessionmaker(bind=engine)()
    target = PlanRecord(
        filename_hash=compute_plan_filename_hash("2026-05-06_fix-target.md"),
        file_path="/repo/docs/archive/2026-05-06_fix-target.md",
        raw_content="# target",
    )
    source = PlanRecord(
        filename_hash=compute_plan_filename_hash("2026-05-06_fix-source.md"),
        file_path="/repo/docs/archive/2026-05-06_fix-source.md",
        raw_content="직접 선행: 2026-05-06_fix-target.md",
    )
    session.add_all([target, source])
    session.commit()
    session.close()
    engine.dispose()
    return db_path


def test_dry_run_does_not_mutate_db(tmp_path):
    db_path = _seed(tmp_path)

    summary = reindex.run(database_url=f"sqlite:///{db_path}", apply=False)

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session = sessionmaker(bind=engine)()
    try:
        assert summary["dry_run"] is True
        assert summary["created"] >= 1
        assert session.query(PlanRecordRelation).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_apply_upserts_relations(tmp_path):
    db_path = _seed(tmp_path)

    summary = reindex.run(database_url=f"sqlite:///{db_path}", apply=True, relation_type="predecessor")

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session = sessionmaker(bind=engine)()
    try:
        assert summary["dry_run"] is False
        assert session.query(PlanRecordRelation).filter_by(relation_type="predecessor").count() == 1
    finally:
        session.close()
        engine.dispose()


def test_run_uses_config_database_url_when_omitted(monkeypatch, tmp_path):
    db_path = _seed(tmp_path)
    monkeypatch.setattr(reindex.settings, "DATABASE_URL", f"sqlite:///{db_path}")

    summary = reindex.run(apply=False, limit=1)

    assert summary["dry_run"] is True
    assert summary["record_count"] == 1

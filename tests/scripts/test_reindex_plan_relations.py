from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "plan_runner"))

import reindex_plan_relations as reindex  # noqa: E402
from app.models.plan_record import PlanRecord, PlanRecordRelation  # noqa: E402
from app.modules.dev_runner.services.plan_archive_relation_service import compute_plan_filename_hash  # noqa: E402


def _seed(tmp_path, *, source_content: str = "직접 선행: 2026-05-06_fix-target.md"):
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
        raw_content=source_content,
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


def test_main_apply_json_uses_config_database_url(monkeypatch, tmp_path, capsys):
    db_path = _seed(tmp_path)
    monkeypatch.setattr(reindex.settings, "DATABASE_URL", f"sqlite:///{db_path}")

    exit_code = reindex.main(["--apply", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is False
    assert payload["record_count"] == 2
    assert "created" in payload


def test_main_json_stdout_is_valid_json(monkeypatch, tmp_path, capsys):
    db_path = _seed(tmp_path)
    monkeypatch.setattr(reindex.settings, "DATABASE_URL", f"sqlite:///{db_path}")

    reindex.main(["--json", "--limit", "1"])

    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert stdout.lstrip().startswith("{")
    assert payload["dry_run"] is True
    assert "details" not in payload


def test_main_deduplicates_repeated_mentions(tmp_path, capsys):
    repeated_content = "\n".join(
        [
            "직접 선행: 2026-05-06_fix-target.md",
            "",
            "관련 계획: 2026-05-06_fix-target.md",
            "",
            "다시 언급: 2026-05-06_fix-target.md",
            "",
            "선행 계획서: 2026-05-06_fix-target.md",
        ]
    )
    db_path = _seed(tmp_path, source_content=repeated_content)

    exit_code = reindex.main(["--database-url", f"sqlite:///{db_path}", "--apply", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] == 2
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session = sessionmaker(bind=engine)()
    try:
        source = session.query(PlanRecord).filter(PlanRecord.file_path.like("%fix-source.md")).one()
        target = session.query(PlanRecord).filter(PlanRecord.file_path.like("%fix-target.md")).one()
        rows = (
            session.query(PlanRecordRelation)
            .filter_by(source_plan_record_id=source.id, target_plan_record_id=target.id)
            .all()
        )
        relation_types = {row.relation_type for row in rows}
        assert relation_types == {"mentions", "predecessor"}
        assert len(rows) == 2
    finally:
        session.close()
        engine.dispose()


def test_main_details_flag_preserves_record_details(tmp_path, capsys):
    db_path = _seed(tmp_path)

    reindex.main(["--database-url", f"sqlite:///{db_path}", "--json", "--details"])

    payload = json.loads(capsys.readouterr().out)
    assert "details" in payload
    assert len(payload["details"]) == payload["record_count"]


def test_main_record_id_relation_type_filters_target_rows(tmp_path, capsys):
    db_path = _seed(tmp_path)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session = sessionmaker(bind=engine)()
    try:
        source = session.query(PlanRecord).filter(PlanRecord.file_path.like("%fix-source.md")).one()
        source_id = source.id
    finally:
        session.close()
        engine.dispose()

    exit_code = reindex.main(
        [
            "--database-url",
            f"sqlite:///{db_path}",
            "--record-id",
            str(source_id),
            "--relation-type",
            "predecessor",
            "--apply",
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["record_count"] == 1
    assert payload["relation_types"] == ["predecessor"]
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session = sessionmaker(bind=engine)()
    try:
        assert session.query(PlanRecordRelation).filter_by(relation_type="predecessor").count() == 1
        assert session.query(PlanRecordRelation).filter_by(relation_type="mentions").count() == 0
    finally:
        session.close()
        engine.dispose()

from datetime import datetime, timedelta
import subprocess

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanRecord, PlanRecordChunk, PlanRecordFileRef, PlanRecordRelation, PlanRecordSearchRun
from app.modules.dev_runner.services.plan_archive_index_service import PlanArchiveIndexService
from app.modules.dev_runner.services.plan_archive_metrics_service import PlanArchiveMetricsService
from app.modules.dev_runner.services.plan_archive_retrieval_service import PlanArchiveRetrievalService, RetrievalQuery


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


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def test_temp_git_repo_plan_and_implementation_commit_indexes_changed_refs(tmp_path):
    db, engine = _make_session()
    try:
        _git(tmp_path, "init")
        _git(tmp_path, "config", "user.email", "test@example.com")
        _git(tmp_path, "config", "user.name", "Test")
        docs_dir = tmp_path / "docs" / "archive"
        docs_dir.mkdir(parents=True)
        plan_file = docs_dir / "2026-01-01-plan.md"
        plan_file.write_text("# Plan\n\n- [ ] `app/service.py`: update", encoding="utf-8")
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        (app_dir / "service.py").write_text("print('v1')\n", encoding="utf-8")
        _git(tmp_path, "add", "docs/archive/2026-01-01-plan.md", "app/service.py")
        _git(tmp_path, "commit", "-m", "feat: implement plan")

        record = PlanRecord(
            filename_hash="git-integration",
            file_path=str(plan_file),
            raw_content=plan_file.read_text(encoding="utf-8"),
            archived_at=datetime.now(),
            status="archived",
        )
        db.add(record)
        db.flush()

        PlanArchiveIndexService(db, tmp_path).index_record(record.id)
        db.flush()

        changed = (
            db.query(PlanRecordFileRef)
            .filter_by(plan_record_id=record.id, source_type="git_changed", path="app/service.py")
            .first()
        )
        assert changed is not None
        assert changed.commit_sha
    finally:
        db.close()
        engine.dispose()


def test_raw_content_chunk_and_file_path_fallback_shape(tmp_path):
    db, engine = _make_session()
    try:
        plan_file = tmp_path / "2026-01-01-plan.md"
        plan_file.write_text("# Plan\n\n- [ ] `app/service.py`: update", encoding="utf-8")
        record = PlanRecord(
            filename_hash="shape",
            file_path=str(plan_file),
            archived_at=datetime.now(),
            status="archived",
            category="infra",
        )
        db.add(record)
        db.flush()
        PlanArchiveIndexService(db, tmp_path).index_record(record.id)
        db.flush()
        result = PlanArchiveRetrievalService(db).search(RetrievalQuery(q="service", category="infra"))
        assert result["total"] == 1
        assert result["results"][0]["chunks"][0]["id"]
    finally:
        db.close()
        engine.dispose()


def test_same_file_group_reappears_within_14_days_metrics(tmp_path):
    db, engine = _make_session()
    try:
        first = PlanRecord(
            filename_hash="r1",
            file_path="docs/archive/a.md",
            archived_at=datetime(2026, 1, 1),
            status="archived",
            category="infra",
        )
        second = PlanRecord(
            filename_hash="r2",
            file_path="docs/archive/b.md",
            archived_at=datetime(2026, 1, 1) + timedelta(days=10),
            status="archived",
            category="infra",
        )
        db.add_all([first, second])
        db.flush()
        db.add_all(
            [
                PlanRecordFileRef(plan_record_id=first.id, source_type="git_changed", path="app/a.py", module="app"),
                PlanRecordFileRef(plan_record_id=second.id, source_type="git_changed", path="app/b.py", module="app"),
            ]
        )
        db.flush()
        metrics = PlanArchiveMetricsService(db).calculate(RetrievalQuery(category="infra"))
        assert metrics["followup_rates"]["days_14"] > 0
        assert metrics["followup_rates"]["days_7"] == 0
    finally:
        db.close()
        engine.dispose()


def test_fts_unavailable_fallback_search_returns_results():
    db, engine = _make_session()
    try:
        record = PlanRecord(
            filename_hash="fallback",
            file_path="docs/archive/fallback.md",
            archived_at=datetime.now(),
            status="archived",
        )
        db.add(record)
        db.flush()
        db.add(
            PlanRecordChunk(
                plan_record_id=record.id,
                chunk_index=0,
                section_type="body",
                heading="Fallback",
                text="fallback lexical search",
                content_hash="h",
                token_estimate=3,
            )
        )
        db.flush()
        result = PlanArchiveRetrievalService(db).search(RetrievalQuery(q="lexical"))
        assert result["total"] == 1
    finally:
        db.close()
        engine.dispose()

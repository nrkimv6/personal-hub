"""Phase T3: raw_content/rotation/restore 통합 TC

in-memory SQLite (DB 격리) + 실제 archive fixture 사용.
실제 DB 의존성 없이 서비스 레이어 통합 동작을 검증.
mock은 git rm/commit (외부 side-effect)만.
"""
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanRecord, PlanEvent
from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.dev_runner.services.plan_record_service import PlanRecordService, _compute_filename_hash


def _create_plan_tables(eng):
    PlanRecord.__table__.create(bind=eng, checkfirst=True)
    PlanEvent.__table__.create(bind=eng, checkfirst=True)
    LLMRequest.__table__.create(bind=eng, checkfirst=True)
    TaskSchedule.__table__.create(bind=eng, checkfirst=True)
    TaskScheduleRun.__table__.create(bind=eng, checkfirst=True)


@pytest.fixture(scope="module")
def int_engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    _create_plan_tables(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def int_db(int_engine):
    Session = sessionmaker(bind=int_engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def int_svc(int_db):
    return PlanRecordService(int_db)


class TestRotationRoundtripIntegration:

    def test_rotation_roundtrip_integration(self, int_svc, int_db, tmp_path):
        """통합: archive fixture 5건 → file_removed_at 마킹 → restore → 원본 내용 일치

        git rm은 외부 side-effect이므로 파일 자체는 삭제하지 않고
        DB 레코드의 file_removed_at만 조작하여 로테이션 상태를 시뮬레이션.
        """
        fixture_records = []
        for i in range(5):
            fp = tmp_path / f"2026-01-{i+10:02d}-integration-test.md"
            content = f"# Integration Test Plan {i}\n\ncontent_{i}"
            fp.write_text(content, encoding="utf-8")

            record = int_svc.mark_archived(
                str(fp),
                str(fp),
                raw_content=content,
            )
            # archived_at을 91일 전으로 조작
            record.archived_at = datetime.now() - timedelta(days=91)
            int_db.flush()
            fixture_records.append((record, content, fp))

        int_db.commit()

        # 2. 로테이션 대상 쿼리 확인
        targets = int_db.query(PlanRecord).filter(
            PlanRecord.file_removed_at.is_(None),
            PlanRecord.archived_at < datetime.now() - timedelta(days=90),
            PlanRecord.raw_content.isnot(None),
            PlanRecord.id.in_([r[0].id for r in fixture_records]),
        ).all()
        assert len(targets) == 5, "5건 모두 로테이션 대상이어야 함"

        # 3. file_removed_at 마킹 (로테이션 시뮬레이션)
        now = datetime.now()
        for rec, content, fp in fixture_records:
            rec.file_removed_at = now
        int_db.commit()

        # 4. restore → 원본 내용 일치
        for rec, content, fp in fixture_records:
            restored = int_svc.restore_file(rec.id)
            int_db.flush()

            assert restored is not None
            assert restored.file_removed_at is None
            assert fp.read_text(encoding="utf-8") == content, f"복원 내용 불일치: {fp.name}"

        int_db.commit()

    def test_ingest_single_integration(self, int_svc, int_db, tmp_path):
        """통합: ingest_single → DB 저장 → get_record 조회 → raw_content 일치"""
        fp = tmp_path / "2026-01-20-ingest-integration.md"
        content = "# Ingest Integration\n\nsome content"
        fp.write_text(content, encoding="utf-8")

        record = int_svc.ingest_single(
            file_path=str(fp),
            project="test-project",
            raw_content=content,
            title="Ingest Integration",
        )
        int_db.commit()

        fetched = int_svc.get_record(record.id)
        assert fetched is not None
        assert fetched.raw_content == content
        assert fetched.project == "test-project"

    def test_ingest_single_updates_plan_to_archive_path_integration(self, int_svc, int_db, tmp_path):
        """통합: 같은 filename hash의 plan record를 archive ingest가 갱신한다."""
        plan_dir = tmp_path / "docs" / "plan"
        archive_dir = tmp_path / "docs" / "archive"
        plan_dir.mkdir(parents=True)
        archive_dir.mkdir(parents=True)

        filename = "2026-05-03_archive-path-integration.md"
        plan_path = plan_dir / filename
        archive_path = archive_dir / filename
        plan_path.write_text("# Active Plan\n\nold body", encoding="utf-8")
        archive_path.write_text("# Archived Plan\n\nnew body", encoding="utf-8")

        active = int_svc.get_or_create(str(plan_path), title="Active Plan", project="monitor-page")
        int_db.flush()

        assert _compute_filename_hash(str(plan_path)) == _compute_filename_hash(str(archive_path))

        updated = int_svc.ingest_single(
            file_path=str(archive_path),
            project="monitor-page",
            raw_content=archive_path.read_text(encoding="utf-8"),
            title="Archived Plan",
            status="archived",
        )
        int_db.commit()

        assert updated.id == active.id
        assert updated.file_path == str(archive_path)
        assert updated.raw_content == "# Archived Plan\n\nnew body"
        assert updated.archived_at is not None

        count = int_db.query(PlanRecord).filter_by(
            filename_hash=_compute_filename_hash(str(plan_path))
        ).count()
        assert count == 1

    def test_deep_search_integration(self, int_svc, int_db, tmp_path):
        """통합: deep=True 검색 → raw_content 키워드 매칭"""
        unique_kw = "DEEP_SEARCH_INTEGRATION_KW_XYZ_T3"
        fp = tmp_path / "2026-01-21-deep-integration.md"
        content = f"# Deep Search\n\n{unique_kw} is in raw_content"
        fp.write_text(content, encoding="utf-8")

        record = int_svc.mark_archived(str(fp), str(fp), raw_content=content)
        int_db.commit()

        results_deep = int_svc.list_records(q=unique_kw, deep=True, exclude_temp=False)
        assert any(r.id == record.id for r in results_deep), "deep=True → raw_content 히트 필요"

        results_shallow = int_svc.list_records(q=unique_kw, deep=False, exclude_temp=False)
        assert not any(r.id == record.id for r in results_shallow), "deep=False → raw_content 미스캔"

    def test_archive_health_reports_readiness_without_blocking_rotation_counts(self, int_svc, int_db, tmp_path):
        """T3: retrieval readiness warning coexists with archive rotation health counts."""
        fp = tmp_path / "2026-05-06-health-rotation.md"
        content = "# Rotation Health\n\ncontent"
        fp.write_text(content, encoding="utf-8")

        record = int_svc.mark_archived(str(fp), str(fp), raw_content=content)
        record.llm_processed_at = datetime.now() - timedelta(days=8)
        record.file_delete_after = datetime.now() - timedelta(days=1)
        int_db.commit()

        health = int_svc.get_plan_archive_health()

        assert health["file_retention_due"] >= 1
        assert health["retrieval_db_readiness"]["ok"] is False
        assert "plan_record_file_refs" in health["retrieval_db_readiness"]["missing_tables"]

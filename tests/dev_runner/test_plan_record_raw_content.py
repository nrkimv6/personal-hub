"""PlanRecord raw_content / rotation / restore / deep search / ingest_single 유닛테스트
— RIGHT-BICEP + CORRECT

대상 소스:
  app/modules/dev_runner/services/plan_record_service.py
  scripts/services/rotate_archive_files.py
"""
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanRecord, PlanEvent
from app.modules.dev_runner.services.plan_record_service import (
    PlanRecordService,
    _compute_filename_hash,
)


def _create_plan_tables(eng):
    PlanRecord.__table__.create(bind=eng, checkfirst=True)
    PlanEvent.__table__.create(bind=eng, checkfirst=True)


# ========== Fixtures ==========

@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    _create_plan_tables(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def svc(db):
    return PlanRecordService(db)


# ========== Phase 2: raw_content ingest ==========

class TestMarkArchivedRawContent:

    def test_plan_record_raw_content_ingest_right(self, svc, db):
        """R: mark_archived() 호출 시 raw_content 파라미터 → record.raw_content 저장"""
        fp = "/plan/2026-01-10-test-raw.md"
        content = "# Test Plan\n\nsome content"

        record = svc.mark_archived(fp, "/archive/2026-01-10-test-raw.md", raw_content=content)
        db.flush()

        assert record is not None
        assert record.raw_content == content

    def test_plan_record_raw_content_none_skips_update(self, svc, db):
        """B: raw_content=None 이면 raw_content 필드를 건드리지 않음"""
        fp = "/plan/2026-01-11-test-none.md"
        record = svc.mark_archived(fp, "/archive/2026-01-11-test-none.md", raw_content=None)
        db.flush()

        assert record.raw_content is None


# ========== Phase 2: backfill idempotency ==========

class TestBackfillIdempotency:

    def test_plan_record_raw_content_backfill_idempotent(self, svc, db, tmp_path):
        """B: 이미 raw_content가 있는 레코드는 backfill 스크립트에서 skip"""
        # 파일 생성
        f = tmp_path / "2026-01-12-existing-content.md"
        f.write_text("# Already filled", encoding="utf-8")

        fp = str(f)
        record = svc.get_or_create(fp)
        record.raw_content = "original content"
        db.flush()

        # backfill 로직 시뮬레이션: raw_content IS NOT NULL → skip
        targets = db.query(PlanRecord).filter(PlanRecord.raw_content.is_(None)).all()
        fp_set = {r.file_path for r in targets}
        assert fp not in fp_set, "이미 raw_content 있는 레코드는 backfill 대상 아님"


# ========== Phase 3: restore_file ==========

class TestRestoreFile:

    def test_restore_api_right(self, svc, db, tmp_path):
        """R: restore_file() → 파일 재생성, file_removed_at 초기화"""
        archive_path = tmp_path / "2026-01-13-restore-test.md"
        content = "# Restore Test\n\ncontent to restore"

        record = svc.mark_archived(
            "/plan/2026-01-13-restore-test.md",
            str(archive_path),
            raw_content=content,
        )
        record.file_removed_at = datetime.now()
        db.flush()

        restored = svc.restore_file(record.id)
        db.flush()

        assert restored is not None
        assert restored.file_removed_at is None
        assert archive_path.exists()
        assert archive_path.read_text(encoding="utf-8") == content

    def test_restore_no_content_returns_none(self, svc, db):
        """E: raw_content IS NULL인 레코드 → restore_file() returns None"""
        fp = "/plan/2026-01-14-no-content.md"
        record = svc.get_or_create(fp)
        db.flush()

        result = svc.restore_file(record.id)
        assert result is None

    def test_restore_nonexistent_record_returns_none(self, svc, db):
        """E: 존재하지 않는 record_id → restore_file() returns None"""
        result = svc.restore_file(99999999)
        assert result is None


# ========== Phase 3: GET /content API ==========

class TestContentApi:

    def test_content_api_right(self, svc, db):
        """R: get_record() 후 raw_content 반환 (라우트 로직 검증)"""
        fp = "/plan/2026-01-15-content-api.md"
        content = "# Content API Test"
        record = svc.mark_archived(fp, "/archive/2026-01-15-content-api.md", raw_content=content)
        db.flush()

        fetched = svc.get_record(record.id)
        assert fetched is not None
        assert fetched.raw_content == content


# ========== Phase 3: deep search ==========

class TestDeepSearch:

    def test_search_deep_true_scans_raw_content(self, svc, db):
        """R: deep=True → raw_content까지 스캔"""
        fp = "/plan/2026-01-16-deep-search.md"
        unique_keyword = "UNIQUE_KEYWORD_XYZ_DEEP_TEST"
        record = svc.mark_archived(fp, "/archive/2026-01-16-deep-search.md", raw_content=f"# Plan\n{unique_keyword}")
        db.flush()

        results = svc.list_records(q=unique_keyword, deep=True)
        ids = [r.id for r in results]
        assert record.id in ids

    def test_search_deep_false_scans_summary_only(self, svc, db):
        """B: deep=False(default) → raw_content 미스캔, summary/title만"""
        fp = "/plan/2026-01-17-shallow-search.md"
        unique_keyword = "UNIQUE_KEYWORD_XYZ_SHALLOW_TEST"
        # raw_content에만 키워드가 있고 summary/title에는 없음
        record = svc.mark_archived(fp, "/archive/2026-01-17-shallow-search.md", raw_content=f"# Plan\n{unique_keyword}")
        db.flush()

        results = svc.list_records(q=unique_keyword, deep=False)
        ids = [r.id for r in results]
        assert record.id not in ids


# ========== Phase 3: ingest_single ==========

class TestIngestSingle:

    def test_ingest_single_api_right(self, svc, db):
        """R: ingest_single() → PlanRecord 생성 + raw_content 저장"""
        fp = "/plan/2026-01-18-ingest-single.md"
        content = "# Ingest Single Test"
        record = svc.ingest_single(
            file_path=fp,
            project="test-project",
            raw_content=content,
            title="Ingest Single Test",
            status="archived",
        )
        db.flush()

        assert record.id is not None
        assert record.raw_content == content
        assert record.project == "test-project"
        assert record.status == "archived"

    def test_ingest_single_api_upsert(self, svc, db):
        """B: 동일 file_path 2회 호출 → update (중복 생성 아님)"""
        fp = "/plan/2026-01-19-ingest-upsert.md"
        r1 = svc.ingest_single(file_path=fp, project="proj1", raw_content="first")
        db.flush()

        r2 = svc.ingest_single(file_path=fp, project="proj2", raw_content="second")
        db.flush()

        assert r1.id == r2.id
        assert r2.project == "proj2"
        assert r2.raw_content == "second"

        # DB에 레코드가 1개만 있어야 함
        count = db.query(PlanRecord).filter(
            PlanRecord.filename_hash == _compute_filename_hash(fp)
        ).count()
        assert count == 1


# ========== Phase 4: rotation trigger ==========

class TestRotationTrigger:
    """rotate_archive_files.py 핵심 로직 단위 테스트 (subprocess 미사용)"""

    def _make_due_archived_record(self, db, fp: str, days_due: int = 1) -> PlanRecord:
        """로테이션 대상 레코드 생성 헬퍼"""
        processed_at = datetime.now() - timedelta(days=8)
        record = PlanRecord(
            filename_hash=_compute_filename_hash(fp),
            file_path=fp,
            status="archived",
            archived_at=datetime.now() - timedelta(days=10),
            llm_processed_at=processed_at,
            file_delete_after=datetime.now() - timedelta(days=days_due),
            raw_content="# Archive content",
        )
        db.add(record)
        db.flush()
        return record

    def test_rotation_targets_use_file_delete_after_right(self, db):
        """R: due file_delete_after records are rotation targets."""
        from scripts.services.rotate_archive_files import get_rotation_targets
        record = self._make_due_archived_record(db, "/archive/2026-01-20-rot-right.md")

        targets = get_rotation_targets(db)

        assert any(target.id == record.id for target in targets)

    def test_rotation_skips_future_file_delete_after(self, db):
        """B: future file_delete_after records are not due."""
        fp = "/archive/2026-01-21-recent.md"
        record = PlanRecord(
            filename_hash=_compute_filename_hash(fp),
            file_path=fp,
            status="archived",
            archived_at=datetime.now() - timedelta(days=10),
            llm_processed_at=datetime.now() - timedelta(days=1),
            file_delete_after=datetime.now() + timedelta(days=6),
            raw_content="# Recent content",
        )
        db.add(record)
        db.flush()

        from scripts.services.rotate_archive_files import get_rotation_targets
        targets = get_rotation_targets(db)

        assert not any(target.id == record.id for target in targets)

    def test_rotation_skips_if_no_raw_content(self, db):
        """E: raw_content IS NULL인 레코드는 대상 제외 (안전장치)"""
        fp = "/archive/2026-01-22-no-raw.md"
        record = PlanRecord(
            filename_hash=_compute_filename_hash(fp),
            file_path=fp,
            status="archived",
            archived_at=datetime.now() - timedelta(days=10),
            llm_processed_at=datetime.now() - timedelta(days=8),
            file_delete_after=datetime.now() - timedelta(days=1),
            raw_content=None,  # raw_content 없음
        )
        db.add(record)
        db.flush()

        from scripts.services.rotate_archive_files import get_rotation_targets
        targets = get_rotation_targets(db)

        assert not any(target.id == record.id for target in targets), "raw_content 없는 레코드는 로테이션 대상 아님"

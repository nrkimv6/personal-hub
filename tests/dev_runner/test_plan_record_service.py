"""PlanRecordService 유닛테스트 — RIGHT-BICEP + Correct

대상 소스: app/modules/dev_runner/services/plan_record_service.py
"""
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanRecord, PlanEvent
from app.modules.dev_runner.services.plan_record_service import (
    PlanRecordService,
    _compute_filename_hash,
)


def _create_plan_tables(eng):
    """PlanRecord, PlanEvent 테이블만 생성 (전체 Base 사용 불가 — FK 해결 문제)"""
    PlanRecord.__table__.create(bind=eng, checkfirst=True)
    PlanEvent.__table__.create(bind=eng, checkfirst=True)


# ========== Fixtures ==========

@pytest.fixture(scope="module")
def engine():
    """in-memory SQLite 엔진 (plan_records 테이블만)"""
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    _create_plan_tables(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    """매 테스트마다 롤백되는 세션"""
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def svc(db):
    return PlanRecordService(db)


# ========== _compute_filename_hash ==========

class TestComputeFilenameHash:

    def test_compute_filename_hash_deterministic(self):
        """동일 입력 → 동일 해시 (결정론적)"""
        h1 = _compute_filename_hash("docs/plan/2026-01-01-foo.md")
        h2 = _compute_filename_hash("docs/plan/2026-01-01-foo.md")
        assert h1 == h2

    def test_compute_filename_hash_different_files(self):
        """다른 파일명 → 다른 해시"""
        h1 = _compute_filename_hash("docs/plan/2026-01-01-foo.md")
        h2 = _compute_filename_hash("docs/plan/2026-01-02-bar.md")
        assert h1 != h2

    def test_compute_filename_hash_path_independent(self):
        """파일명이 같으면 경로가 달라도 동일 해시 (파일명 기반)"""
        h1 = _compute_filename_hash("path/a/2026-01-01-foo.md")
        h2 = _compute_filename_hash("path/b/2026-01-01-foo.md")
        assert h1 == h2


# ========== get_or_create ==========

class TestGetOrCreate:

    def test_get_or_create_new_record(self, svc, db):
        """DB에 없는 파일 → 새 레코드 생성 + created 이벤트"""
        record = svc.get_or_create("/plan/2026-01-01-new.md", title="New Plan", project="proj")
        db.flush()

        assert record.id is not None
        assert record.file_path == "/plan/2026-01-01-new.md"
        assert record.title == "New Plan"
        assert record.project == "proj"

        events = db.query(PlanEvent).filter_by(plan_record_id=record.id).all()
        assert any(e.event_type == "created" for e in events)

    def test_get_or_create_existing_record(self, svc, db):
        """이미 존재 → 기존 레코드 반환 (중복 생성 없음)"""
        r1 = svc.get_or_create("/plan/2026-01-02-exist.md")
        db.flush()
        r2 = svc.get_or_create("/plan/2026-01-02-exist.md")
        db.flush()

        assert r1.id == r2.id
        events = db.query(PlanEvent).filter_by(plan_record_id=r1.id, event_type="created").all()
        assert len(events) == 1  # created 이벤트 1개만

    def test_get_or_create_path_changed(self, svc, db):
        """파일 이동 감지: 같은 파일명, 다른 경로 → path_changed 이벤트"""
        svc.get_or_create("/old/path/2026-01-03-move.md")
        db.flush()
        record = svc.get_or_create("/new/path/2026-01-03-move.md")
        db.flush()

        events = db.query(PlanEvent).filter_by(plan_record_id=record.id).all()
        assert any(e.event_type == "path_changed" for e in events)
        assert record.file_path == "/new/path/2026-01-03-move.md"


# ========== update_memo_draft ==========

class TestUpdateMemoDraft:

    def test_update_memo_draft(self, svc, db):
        """draft 저장 → memo_draft 갱신, memo 불변"""
        record = svc.get_or_create("/plan/2026-01-04-draft.md")
        db.flush()
        record.memo = "확정 메모"

        result = svc.update_memo_draft(record.id, "임시 저장 내용")
        assert result.memo_draft == "임시 저장 내용"
        assert result.memo == "확정 메모"  # 불변

    def test_update_memo_draft_not_found(self, svc, db):
        """존재하지 않는 record_id → None 반환"""
        result = svc.update_memo_draft(99999, "내용")
        assert result is None


# ========== confirm_memo ==========

class TestConfirmMemo:

    def test_confirm_memo(self, svc, db):
        """draft → memo 확정, memo_draft 초기화, memo_updated 이벤트"""
        record = svc.get_or_create("/plan/2026-01-05-confirm.md")
        db.flush()
        record.memo_draft = "새로운 확정 내용"
        db.flush()

        result = svc.confirm_memo(record.id)
        db.flush()
        assert result.memo == "새로운 확정 내용"
        assert result.memo_draft is None

        events = db.query(PlanEvent).filter_by(plan_record_id=record.id, event_type="memo_updated").all()
        assert len(events) == 1

    def test_confirm_memo_empty_draft(self, svc, db):
        """draft가 None인 상태에서 confirm → 기존 memo 유지"""
        record = svc.get_or_create("/plan/2026-01-06-empty-draft.md")
        db.flush()
        record.memo = "기존 확정 메모"
        record.memo_draft = None

        result = svc.confirm_memo(record.id)
        # draft가 없으면 old_memo 유지
        assert result.memo == "기존 확정 메모"

    def test_confirm_memo_not_found(self, svc, db):
        """존재하지 않는 record_id → None 반환"""
        result = svc.confirm_memo(99999)
        assert result is None


# ========== rollback_memo ==========

class TestRollbackMemo:

    def test_rollback_memo(self, svc, db):
        """memo_draft를 확정 memo로 되돌림"""
        record = svc.get_or_create("/plan/2026-01-07-rollback.md")
        db.flush()
        record.memo = "확정된 메모"
        record.memo_draft = "미확정 임시 내용"

        result = svc.rollback_memo(record.id)
        assert result.memo_draft == "확정된 메모"

    def test_rollback_memo_no_confirmed(self, svc, db):
        """확정 memo 없을 때 롤백 → memo_draft를 빈 문자열로"""
        record = svc.get_or_create("/plan/2026-01-08-no-confirmed.md")
        db.flush()
        record.memo = None
        record.memo_draft = "미확정"

        result = svc.rollback_memo(record.id)
        assert result.memo_draft == ""

    def test_rollback_memo_not_found(self, svc, db):
        """존재하지 않는 record_id → None 반환"""
        result = svc.rollback_memo(99999)
        assert result is None


# ========== mark_archived ==========

class TestMarkArchived:

    def test_mark_archived(self, svc, db):
        """archived_at 기록, file_path 갱신, archived 이벤트"""
        svc.get_or_create("/plan/2026-01-09-archive.md")
        db.flush()

        result = svc.mark_archived(
            "/plan/2026-01-09-archive.md",
            "/archive/2026-01-09-archive.md"
        )
        db.flush()

        assert result.archived_at is not None
        assert result.file_path == "/archive/2026-01-09-archive.md"

        events = db.query(PlanEvent).filter_by(plan_record_id=result.id, event_type="archived").all()
        assert len(events) == 1

    def test_mark_archived_already_archived(self, svc, db):
        """이미 archived인 레코드 재처리 → 덮어쓰기 가능"""
        svc.get_or_create("/plan/2026-01-10-rearchive.md")
        db.flush()

        r1 = svc.mark_archived("/plan/2026-01-10-rearchive.md", "/archive/2026-01-10-rearchive.md")
        db.flush()
        archived_at_1 = r1.archived_at

        import time
        time.sleep(0.01)
        r2 = svc.mark_archived("/plan/2026-01-10-rearchive.md", "/archive2/2026-01-10-rearchive.md")
        db.flush()

        # 두 번째 호출도 정상 처리됨
        assert r2.file_path == "/archive2/2026-01-10-rearchive.md"
        assert r2.archived_at is not None

    def test_mark_archived_no_prior_record(self, svc, db):
        """get_or_create 없이 mark_archived 직접 호출 → 새 레코드 생성"""
        result = svc.mark_archived(
            "/plan/2026-01-11-no-prior.md",
            "/archive/2026-01-11-no-prior.md"
        )
        db.flush()

        assert result is not None
        assert result.archived_at is not None


# ========== sync_all ==========

class TestSyncAll:

    def test_sync_all_new_files(self, svc, db, tmp_path):
        """DB에 없는 파일 → 새 레코드 생성"""
        plan_dir = tmp_path / "plans"
        plan_dir.mkdir()
        (plan_dir / "2026-01-12-sync-new.md").write_text("# Plan A", encoding="utf-8")

        result = svc.sync_all([{"path": str(plan_dir), "type": "plan"}])

        assert result["created"] >= 1
        assert result["missing"] == 0

    def test_sync_all_moved_file(self, svc, db, tmp_path):
        """file_path 불일치 → path_changed 이벤트"""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()

        filename = "2026-01-13-moved.md"
        old_file = old_dir / filename
        old_file.write_text("# Old", encoding="utf-8")

        # DB에 old_dir 경로로 등록
        svc.get_or_create(str(old_file))
        db.flush()

        # 파일을 new_dir로 이동
        new_file = new_dir / filename
        new_file.write_text("# New", encoding="utf-8")
        old_file.unlink()

        result = svc.sync_all([{"path": str(new_dir), "type": "plan"}])

        assert result["updated"] >= 1

    def test_sync_all_missing_file(self, svc, db, tmp_path):
        """파일이 삭제됨 → missing 이벤트"""
        plan_dir = tmp_path / "ghost_plans"
        plan_dir.mkdir()

        # DB에 존재하지만 파일은 없는 레코드 생성
        svc.get_or_create(str(plan_dir / "2026-01-14-ghost.md"))
        db.flush()

        # 빈 폴더로 동기화 (해당 파일 없음)
        result = svc.sync_all([{"path": str(plan_dir), "type": "plan"}])

        assert result["missing"] >= 1

    def test_sync_all_empty_folders(self, svc, db, tmp_path):
        """빈 폴더 → 아무것도 생성/갱신 안 됨"""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        result = svc.sync_all([{"path": str(empty_dir), "type": "plan"}])

        assert result["created"] == 0
        assert result["updated"] == 0

    def test_sync_all_nonexistent_path(self, svc, db, tmp_path):
        """존재하지 않는 경로 → 스킵 (에러 없음)"""
        result = svc.sync_all([{"path": str(tmp_path / "nonexistent"), "type": "plan"}])
        assert result["created"] == 0


# ========== list_records / list_events ==========

class TestListRecordsAndEvents:

    def test_list_records_empty(self, svc, db):
        """레코드가 없으면 빈 목록"""
        result = svc.list_records()
        assert isinstance(result, list)

    def test_list_records_filter_by_project(self, svc, db):
        """project 필터 동작"""
        r = svc.get_or_create("/plan/2026-01-15-proj.md", project="proj-a")
        db.flush()

        results = svc.list_records(project="proj-a")
        ids = [rec.id for rec in results]
        assert r.id in ids

        results_other = svc.list_records(project="proj-b")
        ids_other = [rec.id for rec in results_other]
        assert r.id not in ids_other

    def test_list_events_empty(self, svc, db):
        """이벤트 없으면 빈 목록"""
        result = svc.list_events(event_type="nonexistent_type_xyz")
        assert result == []

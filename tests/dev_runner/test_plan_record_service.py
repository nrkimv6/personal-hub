"""PlanRecordService 유닛테스트 — RIGHT-BICEP + Correct

대상 소스: app/modules/dev_runner/services/plan_record_service.py
"""
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanRecord, PlanEvent
from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.dev_runner.services.plan_record_service import (
    PlanRecordService,
    _compute_filename_hash,
    _is_temp_pytest_path,
    PLAN_FILE_PATTERN,
    EXCLUDE_FILES,
)


def _create_plan_tables(eng):
    """PlanRecord, PlanEvent 테이블만 생성 (전체 Base 사용 불가 — FK 해결 문제)"""
    PlanRecord.__table__.create(bind=eng, checkfirst=True)
    PlanEvent.__table__.create(bind=eng, checkfirst=True)
    TaskSchedule.__table__.create(bind=eng, checkfirst=True)
    TaskScheduleRun.__table__.create(bind=eng, checkfirst=True)
    LLMRequest.__table__.create(bind=eng, checkfirst=True)


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


# ========== ingest_single ==========

class TestIngestSingle:

    def test_ingest_single_updates_existing_record_archive_path(self, svc, db):
        """기존 active record를 archive path ingest로 갱신한다."""
        plan_path = "/workspace/docs/plan/2026-05-03_archive-path-update.md"
        archive_path = "/workspace/docs/archive/2026-05-03_archive-path-update.md"
        record = svc.get_or_create(plan_path, title="Old Title", project="old-project")
        record.file_removed_at = datetime.now()
        record.llm_processed_at = datetime.now() - timedelta(days=1)
        db.flush()

        updated = svc.ingest_single(
            file_path=archive_path,
            project="new-project",
            raw_content="# New Title\n\nnew body",
            title="New Title",
            status="archived",
        )
        db.flush()

        assert updated.id == record.id
        assert updated.file_path == archive_path
        assert updated.raw_content == "# New Title\n\nnew body"
        assert updated.status == "archived"
        assert updated.project == "new-project"
        assert updated.title == "New Title"
        assert updated.archived_at is not None
        assert updated.file_removed_at is None
        assert updated.file_delete_after is not None
        assert updated.file_delete_after > datetime.now()

        count = db.query(PlanRecord).filter(
            PlanRecord.filename_hash == _compute_filename_hash(plan_path)
        ).count()
        assert count == 1

    def test_ingest_single_records_path_changed_event(self, svc, db):
        """archive ingest path 이동은 path_changed와 ingested detail에 남긴다."""
        plan_path = "/workspace/docs/plan/2026-05-03_path-event.md"
        archive_path = "/workspace/docs/archive/2026-05-03_path-event.md"
        record = svc.get_or_create(plan_path)
        db.flush()

        updated = svc.ingest_single(file_path=archive_path, raw_content="# Archived")
        db.flush()

        path_events = db.query(PlanEvent).filter_by(
            plan_record_id=updated.id,
            event_type="path_changed",
        ).all()
        assert len(path_events) == 1
        assert path_events[0].detail == {
            "from": plan_path,
            "to": archive_path,
            "source": "ingest_single",
        }

        ingested = db.query(PlanEvent).filter_by(
            plan_record_id=record.id,
            event_type="ingested",
        ).order_by(PlanEvent.id.desc()).first()
        assert ingested is not None
        assert ingested.detail["updated"] is True
        assert ingested.detail["old_path"] == plan_path
        assert ingested.detail["new_path"] == archive_path

    def test_ingest_single_same_path_does_not_duplicate_path_changed_event(self, svc, db):
        """같은 path 재ingest는 path_changed 이벤트를 추가하지 않는다."""
        archive_path = "/workspace/docs/archive/2026-05-03_same-path.md"

        first = svc.ingest_single(file_path=archive_path, raw_content="first")
        db.flush()
        second = svc.ingest_single(file_path=archive_path, raw_content="second")
        db.flush()

        assert first.id == second.id
        events = db.query(PlanEvent).filter_by(
            plan_record_id=second.id,
            event_type="path_changed",
        ).all()
        assert events == []


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

    def test_sync_all_archive_path_creates_archived_record(self, svc, db, tmp_path):
        """/records/sync가 archive 경로 신규 파일을 archived 상태로 등록한다."""
        archive_dir = tmp_path / "docs" / "archive" / "monitor-page"
        archive_dir.mkdir(parents=True)
        archive_file = archive_dir / "2026-05-06_sync-archive-create.md"
        archive_file.write_text("# Archive Sync Create\n본문", encoding="utf-8")

        result = svc.sync_all([{"path": str(tmp_path / "docs" / "archive"), "type": "archive"}])

        record = db.query(PlanRecord).filter_by(filename_hash=_compute_filename_hash(str(archive_file))).first()
        assert result["archive_created"] == 1
        assert record is not None
        assert record.status == "archived"
        assert record.archived_at is not None
        assert record.category == "monitor-page"
        assert record.raw_content and "Archive Sync Create" in record.raw_content

    def test_sync_all_archive_path_normalizes_existing_planned_record(self, svc, db, tmp_path):
        """기존 planned 레코드가 archive 경로에서 발견되면 archived_at/status를 보정한다."""
        plan_file = tmp_path / "plans" / "2026-05-06_sync-archive-normalize.md"
        plan_file.parent.mkdir()
        plan_file.write_text("# Planned Before Archive\n", encoding="utf-8")
        record = svc.get_or_create(str(plan_file))
        db.flush()
        assert record.status == "planned"

        archive_dir = tmp_path / "docs" / "archive" / "common"
        archive_dir.mkdir(parents=True)
        archive_file = archive_dir / plan_file.name
        archive_file.write_text("# Planned Before Archive\narchived", encoding="utf-8")

        result = svc.sync_all([{"path": str(tmp_path / "docs" / "archive"), "type": "archive"}])
        db.refresh(record)

        assert result["archive_normalized"] == 1
        assert record.status == "archived"
        assert record.archived_at is not None
        assert record.file_path == str(archive_file)
        assert record.raw_content and "archived" in record.raw_content

    def test_list_archive_candidates_combines_files_and_db(self, svc, db, tmp_path):
        """archive 후보 목록은 파일-only, 분석대기 DB 매칭 상태를 함께 반환한다."""
        archive_dir = tmp_path / "docs" / "archive" / "common"
        archive_dir.mkdir(parents=True)
        file_only = archive_dir / "2026-05-06_archive-candidate-file-only.md"
        file_only.write_text("# File Only\n", encoding="utf-8")
        db_ready = archive_dir / "2026-05-06_archive-candidate-db-ready.md"
        db_ready.write_text("# DB Ready\n", encoding="utf-8")
        svc.mark_archived(str(db_ready), str(db_ready), raw_content=db_ready.read_text(encoding="utf-8"))
        db.flush()

        result = svc.list_archive_candidates(
            [{"path": str(tmp_path / "docs" / "archive"), "type": "archive"}],
            include_temp=True,
        )

        by_name = {Path(item["file_path"]).name: item for item in result["candidates"]}
        assert by_name[file_only.name]["state"] == "file_only"
        assert by_name[file_only.name]["eligible_for_import"] is True
        assert by_name[db_ready.name]["eligible_for_analysis"] is True
        assert result["llm_pending"] >= 1

    def test_list_archive_candidates_excludes_pytest_temp_by_default(self, svc, db, tmp_path):
        """후보 목록은 기본값으로 pytest 임시 경로를 숨긴다."""
        archive_dir = tmp_path / "docs" / "archive" / "common"
        archive_dir.mkdir(parents=True)
        archive_file = archive_dir / "2026-05-06_archive-candidate-temp-filter.md"
        archive_file.write_text("# Temp Filter\n", encoding="utf-8")

        result = svc.list_archive_candidates([{"path": str(tmp_path / "docs" / "archive"), "type": "archive"}])

        assert result["total"] == 0


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

    def test_list_records_excludes_temp_pytest_records_by_default(self, svc, db):
        """R: archive 목록 기본 조회는 pytest temp PlanRecord를 제외한다."""
        real = svc.ingest_single(
            file_path=r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\archive\2026-05-05_real.md",
            raw_content="# real",
        )
        temp = svc.ingest_single(
            file_path=r"C:\Users\Narang\AppData\Local\Temp\pytest-of-Narang\pytest-42\docs\archive\2026-05-05_temp.md",
            raw_content="# temp",
        )
        db.flush()

        default_records = svc.list_records(status="archived")
        include_temp_records = svc.list_records(status="archived", exclude_temp=False)

        assert real.id in [record.id for record in default_records]
        assert temp.id not in [record.id for record in default_records]
        assert temp.id in [record.id for record in include_temp_records]

    def test_list_events_empty(self, svc, db):
        """이벤트 없으면 빈 목록"""
        result = svc.list_events(event_type="nonexistent_type_xyz")
        assert result == []


class TestTempPytestPath:
    def test_is_temp_pytest_path_recognizes_windows_pytest_of(self):
        path = r"C:\Users\Narang\AppData\Local\Temp\pytest-of-Narang\pytest-42\docs\archive\a.md"
        assert _is_temp_pytest_path(path) is True

    def test_is_temp_pytest_path_recognizes_linux_tmp(self):
        assert _is_temp_pytest_path("/tmp/pytest-of-user/pytest-1/docs/archive/a.md") is True

    def test_is_temp_pytest_path_rejects_real_archive(self):
        path = r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\archive\2026-05-05_real.md"
        assert _is_temp_pytest_path(path) is False


class TestPlanArchiveHealth:
    def test_get_plan_archive_health_right_counts_real_and_temp_records(self, svc, db):
        """R: health는 real/temp archive와 active/failed request를 분리 집계한다."""
        real_processed = svc.ingest_single(
            file_path="/repo/docs/archive/2026-05-01_real_done.md",
            raw_content="# done",
        )
        real_processed.llm_processed_at = datetime(2026, 5, 2)
        real_pending = svc.ingest_single(
            file_path="/repo/docs/archive/2026-05-02_real_pending.md",
            raw_content="# pending",
        )
        temp_pending = svc.ingest_single(
            file_path=r"C:\Users\Narang\AppData\Local\Temp\pytest-of-Narang\pytest-7\docs\archive\2026-05-03_temp.md",
            raw_content="# temp",
        )
        schedule = TaskSchedule(
            name="plan_archive_analyze_daily",
            display_name="Plan Archive LLM 분석",
            target_type=TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE,
            schedule_type="cron",
            schedule_value='{"time":"02:10"}',
            enabled=False,
            last_run_at=datetime(2026, 5, 4, 2, 10),
        )
        db.add(schedule)
        db.flush()
        db.add_all([
            TaskScheduleRun(
                schedule_id=schedule.id,
                status=TaskScheduleRun.STATUS_COMPLETED,
                finished_at=datetime(2026, 5, 4, 2, 11),
            ),
            TaskScheduleRun(
                schedule_id=schedule.id,
                status=TaskScheduleRun.STATUS_FAILED,
                finished_at=datetime(2026, 5, 3, 2, 11),
            ),
            LLMRequest(caller_type="plan_archive_analyze", caller_id=real_pending.filename_hash, prompt="p", status="pending"),
            LLMRequest(caller_type="plan_archive_analyze", caller_id=temp_pending.filename_hash, prompt="p", status="failed", error_message="boom"),
        ])
        db.flush()

        health = svc.get_plan_archive_health()

        assert health["archived_total"] == 3
        assert health["llm_processed"] == 1
        assert health["llm_unprocessed"] == 2
        assert health["real_unprocessed"] == 1
        assert health["temp_pytest_total"] == 1
        assert health["temp_pytest_unprocessed"] == 1
        assert health["pending_or_processing_requests"] == 1
        assert health["failed_requests"] == 1
        assert health["latest_failed_request"]["error_message"] == "boom"
        assert health["plan_archive_schedule"]["enabled"] is False
        assert health["plan_archive_schedule"]["last_success"] == "2026-05-04T02:11:00"

    def test_get_guide_status_excludes_temp_pytest_records(self, svc, db, monkeypatch):
        """R: guide-status pending archive 후보도 temp PlanRecord를 제외한다."""
        from app.shared import wiki_tags

        monkeypatch.setattr(wiki_tags, "load_meta_yaml", lambda: {
            "dev-guide": {
                "owns_archive_tags": ["plan"],
                "last_archive_scan": "2026-05-01",
            }
        })
        monkeypatch.setattr(wiki_tags, "load_whitelist", lambda: {"plan"})
        monkeypatch.setattr(wiki_tags, "extract_wiki_tags", lambda filename, whitelist: ["plan"])

        svc.ingest_single(
            file_path="/repo/docs/archive/2026-05-02_real-plan.md",
            raw_content="# real",
        )
        svc.ingest_single(
            file_path=r"C:\Users\Narang\AppData\Local\Temp\pytest-of-Narang\pytest-1\docs\archive\2026-05-03_temp-plan.md",
            raw_content="# temp",
        )
        db.flush()

        status = svc.get_guide_status()

        assert status[0]["pending_count"] == 1
        assert "real-plan" in status[0]["pending_archives"][0]["file_path"]


# ========== Phase 1: title/project 자동 파싱 (items 14~16) ==========

class TestGetOrCreateAutoTitleProject:

    def test_get_or_create_auto_title(self, svc, db, tmp_path):
        """title=None으로 호출 시 파일 첫 줄 # 헤더에서 자동 추출 (RIGHT)"""
        plan_file = tmp_path / "2026-03-01-auto-title.md"
        plan_file.write_text("# 자동 추출 계획서\n\n본문 내용", encoding="utf-8")

        record = svc.get_or_create(str(plan_file), title=None)
        db.flush()

        assert record.title == "자동 추출 계획서"

    def test_get_or_create_auto_project(self, svc, db, tmp_path):
        """project=None으로 호출 시 경로의 archive/{project} 패턴에서 자동 추출 (RIGHT)"""
        archive_dir = tmp_path / "docs" / "archive" / "monitor-page"
        archive_dir.mkdir(parents=True)
        plan_file = archive_dir / "2026-03-02-auto-project.md"
        plan_file.write_text("# 프로젝트 자동 감지\n", encoding="utf-8")

        record = svc.get_or_create(str(plan_file), project=None)
        db.flush()

        assert record.project == "monitor-page"

    def test_get_or_create_explicit_title_preserved(self, svc, db, tmp_path):
        """명시적 title 인자가 파일 헤더 자동파싱보다 우선 (RIGHT)"""
        plan_file = tmp_path / "2026-03-03-explicit.md"
        plan_file.write_text("# 파일 헤더 제목\n\n내용", encoding="utf-8")

        record = svc.get_or_create(str(plan_file), title="명시적으로 전달한 제목")
        db.flush()

        assert record.title == "명시적으로 전달한 제목"

    def test_get_or_create_no_header_returns_none_title(self, svc, db, tmp_path):
        """파일에 # 헤더 없고 title=None → title은 None (BOUNDARY)"""
        plan_file = tmp_path / "2026-03-04-no-header.md"
        plan_file.write_text("본문만 있고 헤더 없음\n", encoding="utf-8")

        record = svc.get_or_create(str(plan_file), title=None)
        db.flush()

        assert record.title is None

    def test_sync_all_backfills_title_for_existing_record(self, svc, db, tmp_path):
        """sync_all 시 기존 레코드에 title 없으면 파일에서 백필 (RIGHT)"""
        plan_dir = tmp_path / "plans"
        plan_dir.mkdir()
        plan_file = plan_dir / "2026-03-05-backfill.md"
        plan_file.write_text("# 백필 대상 제목\n", encoding="utf-8")

        # title 없이 먼저 등록
        record = svc.get_or_create(str(plan_file), title=None)
        record.title = None  # 강제로 None 설정
        db.flush()

        svc.sync_all([{"path": str(plan_dir), "type": "plan"}])

        db.refresh(record)
        assert record.title == "백필 대상 제목"


# ========== Phase 2: sync_all 비-plan 파일 필터링 (items 17~19) ==========

class TestSyncAllPlanFileFilter:

    def test_sync_all_excludes_non_plan_files(self, svc, db, tmp_path):
        """CLAUDE.md, CHANGELOG.md 등 제외 파일은 DB에 등록되지 않음 (BOUNDARY)"""
        plan_dir = tmp_path / "plans_filter"
        plan_dir.mkdir()

        # 제외 대상 파일들
        for name in ["CLAUDE.md", "CHANGELOG.md", "README.md", "TODO.md", "DONE.md"]:
            (plan_dir / name).write_text(f"# {name}", encoding="utf-8")

        # 유효한 plan 파일 하나
        (plan_dir / "2026-03-10-valid.md").write_text("# 유효 계획", encoding="utf-8")

        result = svc.sync_all([{"path": str(plan_dir), "type": "plan"}])

        # 유효 파일 1개만 생성
        assert result["created"] == 1

        # 제외 파일들이 DB에 없음
        for name in ["CLAUDE.md", "CHANGELOG.md", "README.md", "TODO.md", "DONE.md"]:
            from app.modules.dev_runner.services.plan_record_service import _compute_filename_hash
            h = _compute_filename_hash(str(plan_dir / name))
            assert db.query(PlanRecord).filter_by(filename_hash=h).first() is None

    def test_sync_all_includes_dated_plan_files(self, svc, db, tmp_path):
        """YYYY-MM-DD_*.md 패턴 파일만 등록 (RIGHT)"""
        plan_dir = tmp_path / "dated_plans"
        plan_dir.mkdir()

        # 날짜 패턴 파일 — 등록 대상
        (plan_dir / "2026-03-06_fix-something.md").write_text("# 날짜 언더스코어", encoding="utf-8")
        (plan_dir / "2026-03-07-fix-something.md").write_text("# 날짜 하이픈", encoding="utf-8")

        # 비-날짜 파일 — 등록 제외
        (plan_dir / "some-plan.md").write_text("# 날짜 없음", encoding="utf-8")
        (plan_dir / "plan.md").write_text("# 짧은 이름", encoding="utf-8")

        result = svc.sync_all([{"path": str(plan_dir), "type": "plan"}])

        assert result["created"] == 2

    def test_bulk_import_excludes_non_plan(self, svc, db, tmp_path):
        """bulk_import_archived도 동일 필터 적용 (RIGHT)"""
        archive_dir = tmp_path / "archive" / "proj"
        archive_dir.mkdir(parents=True)

        # 유효 plan 파일
        (archive_dir / "2026-03-08-some-plan.md").write_text("# 아카이브 계획", encoding="utf-8")

        # 비-plan 파일
        (archive_dir / "CHANGELOG.md").write_text("# changelog", encoding="utf-8")
        (archive_dir / "README.md").write_text("# readme", encoding="utf-8")
        (archive_dir / "not-dated.md").write_text("# 날짜 없음", encoding="utf-8")

        result = svc.bulk_import_archived(str(tmp_path / "archive"))

        # 유효 파일 1개만 created, 나머지는 skipped
        assert result["created"] == 1
        assert result["errors"] == []

        # README.md 등이 DB에 없음
        for name in ["CHANGELOG.md", "README.md", "not-dated.md"]:
            h = _compute_filename_hash(str(archive_dir / name))
            assert db.query(PlanRecord).filter_by(filename_hash=h).first() is None


# ========== TC 24: DB 격리 — production DB 오염 방지 (ERROR) ==========

class TestDbIsolationNoProductionPollution:
    """TC 24: 테스트 실행 후 production DB에 pytest 경로 레코드가 없음을 검증 (ERROR 범주)

    이 파일의 module-local SQLite fixture만 사용해 PlanRecordService를 검증한다.
    공유 test_db_session/test_db_engine fixture를 타면 전체 metadata/bootstrap이 실행되어
    이 pure service 테스트의 timeout 회귀 경로가 다시 열린다.
    """

    def test_temp_plan_record_fixture_uses_module_local_sqlite(self, engine):
        """R: PlanRecordService 테스트 fixture는 module-local SQLite를 사용한다."""
        assert engine.url.get_backend_name() == "sqlite"
        assert engine.url.database in (None, ":memory:")

    def test_db_isolation_no_production_pollution(self, db, tmp_path, request):
        """테스트 DB에 pytest 경로로 레코드를 생성해도 production DB에는 반영되지 않음

        검증 흐름:
        1. module-local SQLite DB로 pytest 경로 레코드 생성
        2. production DB(data/monitor.db)를 직접 열어 해당 경로가 없음 확인
        """
        import sqlite3
        from sqlalchemy import inspect

        assert "test_db_engine" not in request.fixturenames
        assert "test_db_session" not in request.fixturenames
        assert {"plan_events", "plan_records"}.issubset(set(inspect(db.get_bind()).get_table_names()))

        pytest_path = str(tmp_path / "pytest-isolation-check" / "2026-03-30_isolation-tc.md")
        svc = PlanRecordService(db)
        record = svc.get_or_create(pytest_path)
        db.flush()

        assert record is not None, "module-local DB에 레코드가 생성되어야 함"

        # production DB 경로 결정 (존재하지 않을 경우 스킵)
        prod_db_path = Path(__file__).parent.parent.parent / "data" / "monitor.db"
        if not prod_db_path.exists():
            pytest.skip(f"Production DB 없음: {prod_db_path}")

        conn = sqlite3.connect(str(prod_db_path))
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='plan_records'"
            )
            if cursor.fetchone() is None:
                pytest.skip(f"Production DB에 plan_records 테이블 없음: {prod_db_path}")
            cursor.execute(
                "SELECT COUNT(*) FROM plan_records WHERE file_path LIKE '%pytest-isolation-check%'"
            )
            count = cursor.fetchone()[0]
        finally:
            conn.close()

        assert count == 0, (
            f"Production DB에 pytest 경로 레코드가 {count}건 발견됨. "
            "PlanRecordService 테스트가 production DB를 직접 오염시켰을 수 있음."
        )


# ========== Phase 4: status 생명주기 (items 21~23) ==========

class TestUpdateStatus:

    def test_update_status_transition(self, svc, db, tmp_path):
        """planned→in_progress 전이 + 이벤트 기록 (RIGHT, TC 21)"""
        plan_file = tmp_path / "2026-03-20-status-trans.md"
        plan_file.write_text("# 상태 전이 테스트\n", encoding="utf-8")

        record = svc.get_or_create(str(plan_file))
        db.flush()
        assert record.status == "planned"

        result = svc.update_status(str(plan_file), "in_progress")
        db.flush()

        assert result is not None
        assert result.status == "in_progress"

    def test_update_status_event_logged(self, svc, db, tmp_path):
        """상태 변경 시 status_changed 이벤트 detail 확인 (RIGHT, TC 22)"""
        plan_file = tmp_path / "2026-03-21-status-event.md"
        plan_file.write_text("# 이벤트 기록 테스트\n", encoding="utf-8")

        record = svc.get_or_create(str(plan_file))
        db.flush()

        svc.update_status(str(plan_file), "in_progress")
        db.flush()

        events = db.query(PlanEvent).filter_by(
            plan_record_id=record.id, event_type="status_changed"
        ).all()
        assert len(events) == 1
        detail = events[0].detail
        assert detail["from"] == "planned"
        assert detail["to"] == "in_progress"

    def test_sync_from_workflow_mapping(self, svc, db, tmp_path):
        """workflow status→plan_record status 매핑 정확성 (RIGHT, TC 23)"""
        from types import SimpleNamespace

        plan_file = tmp_path / "2026-03-22-workflow-sync.md"
        plan_file.write_text("# 워크플로우 동기화 테스트\n", encoding="utf-8")

        svc.get_or_create(str(plan_file))
        db.flush()

        # running → in_progress
        wf = SimpleNamespace(plan_path=str(plan_file), status="running")
        result = svc.sync_from_workflow(wf)
        db.flush()
        assert result is not None
        assert result.status == "in_progress"

        # completed → completed
        wf.status = "completed"
        result = svc.sync_from_workflow(wf)
        db.flush()
        assert result.status == "completed"

        # failed → planned (재시도 가능)
        wf.status = "failed"
        result = svc.sync_from_workflow(wf)
        db.flush()
        assert result.status == "planned"

"""
PlanRecordService.list_events() pytest 경로 필터링 TC — RIGHT-BICEP 기반

pytest 통합테스트 실행 시 생성되는 임시 경로(AppData\Local\Temp\pytest-of-Narang\ 등)
plan_record에 연결된 이벤트가 list_events() 결과에서 제외되는지 검증.
"""
import pytest
from app.models.plan_record import PlanRecord, PlanEvent
from app.modules.dev_runner.services.plan_record_service import PlanRecordService


def _make_record(db, file_path: str) -> PlanRecord:
    record = PlanRecord(filename_hash=f"hash_{abs(hash(file_path))}", file_path=file_path, title="test")
    db.add(record)
    db.flush()
    return record


def _make_event(db, record: PlanRecord, event_type: str = "created") -> PlanEvent:
    event = PlanEvent(plan_record_id=record.id, event_type=event_type)
    db.add(event)
    db.flush()
    return event


class TestListEventsExcludesPytestPaths:

    def test_list_events_excludes_pytest_temp_path(self, test_db_session):
        """R: AppData\\Temp\\pytest- 경로 plan_record 이벤트 → list_events 결과에서 제외"""
        db = test_db_session
        pytest_path = r"C:\Users\Narang\AppData\Local\Temp\pytest-of-Narang\pytest-42\test_foo\docs\plan\test.md"
        real_path = r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\plan\real_plan.md"

        pytest_rec = _make_record(db, pytest_path)
        real_rec = _make_record(db, real_path)
        _make_event(db, pytest_rec, "created")
        real_evt = _make_event(db, real_rec, "created")

        svc = PlanRecordService(db)
        events = svc.list_events()
        ids = [e.id for e in events]

        assert real_evt.id in ids, "실제 경로 이벤트는 포함되어야 한다"
        assert pytest_rec.id not in [e.plan_record_id for e in events], "pytest 임시 경로 이벤트는 제외되어야 한다"

    def test_list_events_excludes_linux_tmp_pytest_path(self, test_db_session):
        """R: /tmp/pytest- 경로 plan_record 이벤트 → 제외"""
        db = test_db_session
        linux_path = "/tmp/pytest-of-user/pytest-0/test_bar/docs/plan/test.md"
        real_path = r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\archive\2026-01-01_done.md"

        linux_rec = _make_record(db, linux_path)
        real_rec = _make_record(db, real_path)
        _make_event(db, linux_rec, "created")
        real_evt = _make_event(db, real_rec, "archived")

        svc = PlanRecordService(db)
        events = svc.list_events()
        ids = [e.id for e in events]

        assert real_evt.id in ids
        assert linux_rec.id not in [e.plan_record_id for e in events]

    def test_list_events_includes_real_paths(self, test_db_session):
        """R: current plans worktree docs/plan, docs/archive 경로 이벤트 → 포함"""
        db = test_db_session
        paths = [
            r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\plan\2026-03-01_plan.md",
            r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\archive\2026-02-01_done.md",
        ]
        evts = []
        for p in paths:
            rec = _make_record(db, p)
            evts.append(_make_event(db, rec, "created"))

        svc = PlanRecordService(db)
        events = svc.list_events()
        ids = [e.id for e in events]

        for evt in evts:
            assert evt.id in ids, f"실제 경로 이벤트 {evt.id}는 포함되어야 한다"

    def test_list_events_includes_legacy_root_plan_path_as_historical_B(self, test_db_session):
        """B: legacy root docs/plan 경로도 historical path로는 계속 조회된다"""
        db = test_db_session
        legacy_path = r"D:\work\project\tools\monitor-page\docs\plan\2026-03-01_plan.md"

        rec = _make_record(db, legacy_path)
        evt = _make_event(db, rec, "created")

        svc = PlanRecordService(db)
        events = svc.list_events()

        assert evt.id in [event.id for event in events]

    def test_list_events_empty_when_all_pytest(self, test_db_session):
        """E: 전체가 pytest 레코드일 때 빈 리스트 반환"""
        db = test_db_session
        for i in range(3):
            p = rf"C:\Users\Narang\AppData\Local\Temp\pytest-of-Narang\pytest-{i}\test_x\plan.md"
            rec = _make_record(db, p)
            _make_event(db, rec, "created")

        svc = PlanRecordService(db)
        # event_type 필터로 'created'만 조회해도 pytest 경로는 제외
        events = svc.list_events(event_type="created")
        pytest_ids = set()
        for e in events:
            if "pytest-of-Narang" in (e.record.file_path if e.record else ""):
                pytest_ids.add(e.id)

        assert len(pytest_ids) == 0, "pytest 경로 이벤트가 결과에 포함되면 안 된다"

"""schedule_date_expire 통합 테스트 (PostgreSQL).

Phase T3:
1. _execute_schedule_date_expire_run() — past rows disable, today/future 유지
2. integrity fix와 동일 cutoff 기준 검증
3. 0건 실행 및 seed idempotency
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from app.models.business import Business
from app.models.biz_item import BizItem
from app.models.monitor_schedule import MonitorSchedule
from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.services.integrity_check_service import IntegrityCheckService
from app.services.task_schedule_service import TaskScheduleService

_KST = timezone(timedelta(hours=9))

# 고정 cutoff 날짜: 테스트 실행 시각과 무관하게 일관된 결과 보장
_FIXED_CUTOFF = "2026-04-22"
_PAST_DATE = "2026-04-21"       # cutoff 이전 → disable 대상
_TODAY_DATE = "2026-04-22"      # cutoff와 동일 → 유지 (< 조건이므로 제외 안 됨)
_FUTURE_DATE = "2099-12-31"     # 명확히 미래 → 유지


# ──────────────────────────────────────────
# 공용 헬퍼
# ──────────────────────────────────────────

def _make_biz_item(db) -> BizItem:
    uid = uuid.uuid4().hex[:8]
    biz = Business(
        business_id=f"expire-int-biz-{uid}",
        business_type_id=5,
        name=f"Expire Int Biz {uid}",
        service_type="naver",
        is_enabled=True,
    )
    db.add(biz)
    db.flush()

    item = BizItem(
        business_id=biz.id,
        biz_item_id=f"expire-int-item-{uid}",
        name=f"Expire Int Item {uid}",
        is_enabled=True,
    )
    db.add(item)
    db.flush()
    return item


def _add_schedule(db, item: BizItem, date: str, enabled: bool = True) -> MonitorSchedule:
    s = MonitorSchedule(
        biz_item_id=item.id,
        date=date,
        times='["10:00"]',
        is_enabled=enabled,
        run_status="pending",
    )
    db.add(s)
    db.flush()
    return s


def _add_task_schedule(db) -> TaskSchedule:
    uid = uuid.uuid4().hex[:8]
    ts = TaskSchedule(
        name=f"test_expire_{uid}",
        display_name="Test Expire Daily",
        target_type=TaskSchedule.TARGET_TYPE_SCHEDULE_DATE_EXPIRE,
        target_config="{}",
        schedule_type="cron",
        schedule_value='{"time": "01:00"}',
        enabled=True,
    )
    db.add(ts)
    db.flush()
    return ts


# ──────────────────────────────────────────
# TC 1: past rows disable, today/future 유지
# ──────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_execute_disables_only_past_rows_right(test_db_session):
    """R: 과거 날짜 row만 is_enabled=false, 오늘/미래 row는 유지."""
    from app.worker.scheduled_worker import ScheduledCrawlWorker

    item = _make_biz_item(test_db_session)
    past_row = _add_schedule(test_db_session, item, _PAST_DATE)
    today_row = _add_schedule(test_db_session, item, _TODAY_DATE)
    future_row = _add_schedule(test_db_session, item, _FUTURE_DATE)

    ts = _add_task_schedule(test_db_session)
    test_db_session.commit()

    svc = TaskScheduleService(test_db_session)
    run = svc.start_run(
        schedule_id=ts.id,
        worker_id="test_worker",
        config_snapshot={}
    )
    test_db_session.commit()

    worker = ScheduledCrawlWorker.__new__(ScheduledCrawlWorker)
    worker.name = "test_worker"
    worker._tasks = {}
    worker._log_worker_error = MagicMock()

    with patch("app.services.monitor_schedule_cutoff.get_today_kst_iso", return_value=_FIXED_CUTOFF):
        await worker._execute_schedule_date_expire_run(ts, run)

    # 워커 완료 후 test_db_session으로 재조회
    test_db_session.expire_all()
    past_enabled = test_db_session.execute(
        text("SELECT is_enabled FROM monitor_schedules WHERE id = :id"),
        {"id": past_row.id}
    ).scalar()
    today_enabled = test_db_session.execute(
        text("SELECT is_enabled FROM monitor_schedules WHERE id = :id"),
        {"id": today_row.id}
    ).scalar()
    future_enabled = test_db_session.execute(
        text("SELECT is_enabled FROM monitor_schedules WHERE id = :id"),
        {"id": future_row.id}
    ).scalar()
    run_status = test_db_session.execute(
        text("SELECT status FROM task_schedule_runs WHERE id = :id"),
        {"id": run.id}
    ).scalar()

    assert not past_enabled, "과거 row는 비활성화되어야 한다"
    assert today_enabled, "오늘 row는 유지되어야 한다"
    assert future_enabled, "미래 row는 유지되어야 한다"
    assert run_status == TaskScheduleRun.STATUS_COMPLETED


# ──────────────────────────────────────────
# TC 2: integrity fix와 동일 cutoff 기준
# ──────────────────────────────────────────

@pytest.mark.integration
def test_integrity_fix_and_scheduler_target_same_rows_right(test_db_session):
    """R: IntegrityCheckService._check_business_rules()가 scheduler와 동일 cutoff를 사용한다."""
    item = _make_biz_item(test_db_session)
    past = _add_schedule(test_db_session, item, _PAST_DATE, enabled=True)
    _add_schedule(test_db_session, item, _TODAY_DATE, enabled=True)
    test_db_session.commit()

    with patch("app.services.monitor_schedule_cutoff.get_today_kst_iso", return_value=_FIXED_CUTOFF):
        svc = IntegrityCheckService(test_db_session)
        issues = svc._check_business_rules()

    monitor_issues = [
        i for i in issues
        if i.table == "monitor_schedules" and i.issue_type == "invalid_date"
    ]
    detected_ids: set = set()
    for issue in monitor_issues:
        detected_ids.update(issue.sample_ids)

    assert past.id in detected_ids, \
        f"past row(id={past.id})가 integrity_check에서 감지되지 않음"


# ──────────────────────────────────────────
# TC 3: 0건 실행 및 seed idempotency
# ──────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_execute_zero_rows_completes_right(test_db_session):
    """R: 과거 enabled row 0건이면 completed 상태, 에러 없음."""
    from app.worker.scheduled_worker import ScheduledCrawlWorker

    item = _make_biz_item(test_db_session)
    _add_schedule(test_db_session, item, _FUTURE_DATE)
    ts = _add_task_schedule(test_db_session)
    test_db_session.commit()

    svc = TaskScheduleService(test_db_session)
    run = svc.start_run(
        schedule_id=ts.id,
        worker_id="test_worker",
        config_snapshot={}
    )
    test_db_session.commit()

    worker = ScheduledCrawlWorker.__new__(ScheduledCrawlWorker)
    worker.name = "test_worker"
    worker._tasks = {}
    worker._log_worker_error = MagicMock()

    with patch("app.services.monitor_schedule_cutoff.get_today_kst_iso", return_value=_FIXED_CUTOFF):
        await worker._execute_schedule_date_expire_run(ts, run)

    test_db_session.expire_all()
    run_status = test_db_session.execute(
        text("SELECT status FROM task_schedule_runs WHERE id = :id"),
        {"id": run.id}
    ).scalar()

    assert run_status == TaskScheduleRun.STATUS_COMPLETED


@pytest.mark.integration
def test_seed_migration_idempotent_right(test_db_session):
    """R: 121 seed migration을 두 번 실행해도 schedule_date_expire row가 1건으로 유지된다."""
    insert_sql = text("""
        INSERT INTO task_schedules (
            name, display_name, target_type, target_config,
            schedule_type, schedule_value, enabled,
            created_at, updated_at
        ) VALUES (
            'schedule_date_expire_daily',
            '과거 날짜 모니터링 스케줄 자동 비활성화 (매일 01:00)',
            'schedule_date_expire',
            '{}',
            'cron',
            '{"time": "01:00"}',
            true,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        ) ON CONFLICT (name) DO NOTHING
    """)
    test_db_session.execute(insert_sql)
    test_db_session.execute(insert_sql)
    test_db_session.commit()

    count = test_db_session.execute(
        text("SELECT COUNT(*) FROM task_schedules WHERE name = 'schedule_date_expire_daily'")
    ).scalar()

    assert count == 1, f"ON CONFLICT DO NOTHING이 작동하지 않음: {count}건"

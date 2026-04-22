"""Same-date monitor schedule integration tests.

Phase T3 focuses on the post-migration contract:
- same biz_item/date rows can be stored multiple times
- NULL/non-NULL service_account rows can coexist
- worker run-group metadata dedupes by biz_item/date and rotates
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models.business import Business
from app.models.biz_item import BizItem
from app.models.browser_profile import BrowserProfile
from app.models.service_account import ServiceAccount
from app.models.monitor_schedule import MonitorSchedule
from app.worker.naver_monitor_worker import NaverMonitorWorker


@pytest.fixture
def client(test_db_session):
    def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def seeded_schedule_context(test_db_session):
    unique_id = uuid.uuid4().hex[:8]
    business = Business(
        business_id=f"pg-int-biz-{unique_id}",
        business_type_id=5,
        name=f"PG Integration Business {unique_id}",
        service_type="naver",
        is_enabled=True,
    )
    test_db_session.add(business)
    test_db_session.flush()

    item = BizItem(
        business_id=business.id,
        biz_item_id=f"pg-int-item-{unique_id}",
        name=f"PG Integration Item {unique_id}",
        is_enabled=True,
    )
    test_db_session.add(item)
    test_db_session.flush()

    profile = BrowserProfile(
        name=f"PG Integration Profile {unique_id}",
        profile_dir=f"pg_integration_profile_{unique_id}",
        is_active=True,
    )
    test_db_session.add(profile)
    test_db_session.flush()

    account = ServiceAccount(
        profile_id=profile.id,
        service_type="naver",
        identifier=f"pg-integration-{unique_id}@naver.test",
        is_logged_in=True,
    )
    test_db_session.add(account)
    test_db_session.commit()

    return {
        "business": business,
        "item": item,
        "account": account,
    }


@pytest.mark.integration
def test_same_date_rows_are_persisted_after_date_unique_removal(client, test_db_session, seeded_schedule_context):
    item = seeded_schedule_context["item"]

    response1 = client.post(
        f"/api/v1/items/{item.id}/schedules",
        json={
            "date": "2026-04-25",
            "times": ["10:00-12:00"],
            "is_enabled": True,
        },
    )
    response2 = client.post(
        f"/api/v1/items/{item.id}/schedules",
        json={
            "date": "2026-04-25",
            "times": ["17:00-20:00"],
            "is_enabled": True,
        },
    )

    assert response1.status_code == 201
    assert response2.status_code == 201

    rows = (
        test_db_session.query(MonitorSchedule)
        .filter(
            MonitorSchedule.biz_item_id == item.id,
            MonitorSchedule.date == "2026-04-25",
        )
        .order_by(MonitorSchedule.id.asc())
        .all()
    )

    assert len(rows) == 2
    assert sorted(row.times for row in rows) == [
        "[\"10:00-12:00\"]",
        "[\"17:00-20:00\"]",
    ]


@pytest.mark.integration
def test_null_and_non_null_service_account_rows_coexist(client, test_db_session, seeded_schedule_context):
    item = seeded_schedule_context["item"]
    account = seeded_schedule_context["account"]

    without_account = client.post(
        f"/api/v1/items/{item.id}/schedules",
        json={
            "date": "2026-04-26",
            "times": ["09:00"],
            "is_enabled": True,
        },
    )
    with_account = client.post(
        f"/api/v1/items/{item.id}/schedules",
        json={
            "date": "2026-04-26",
            "times": ["11:00"],
            "is_enabled": True,
            "service_account_id": account.id,
        },
    )

    assert without_account.status_code == 201
    assert with_account.status_code == 201

    rows = (
        test_db_session.query(MonitorSchedule)
        .filter(
            MonitorSchedule.biz_item_id == item.id,
            MonitorSchedule.date == "2026-04-26",
        )
        .order_by(MonitorSchedule.id.asc())
        .all()
    )

    assert len(rows) == 2
    assert {row.service_account_id for row in rows} == {None, account.id}

    list_response = client.get(f"/api/v1/items/{item.id}/schedules")
    assert list_response.status_code == 200
    same_date_rows = [
        row for row in list_response.json()
        if row["date"] == "2026-04-26"
    ]
    assert len(same_date_rows) == 2
    assert {row["service_account_id"] for row in same_date_rows} == {None, account.id}


@pytest.mark.integration
def test_worker_run_group_rotation_selects_same_date_rows_in_round_robin(test_db_session, seeded_schedule_context):
    item = seeded_schedule_context["item"]
    account = seeded_schedule_context["account"]

    first = MonitorSchedule(
        biz_item_id=item.id,
        service_account_id=None,
        date="2026-04-27",
        times="[\"09:00\"]",
        is_enabled=True,
        run_status="queued",
    )
    second = MonitorSchedule(
        biz_item_id=item.id,
        service_account_id=account.id,
        date="2026-04-27",
        times="[\"11:00\"]",
        is_enabled=True,
        run_status="queued",
    )
    test_db_session.add_all([first, second])
    test_db_session.commit()
    test_db_session.refresh(first)
    test_db_session.refresh(second)

    worker = NaverMonitorWorker()
    worker._store_active_schedule(
        {
            "id": first.id,
            "biz_item_id": item.id,
            "service_account_id": None,
            "date": first.date,
            "time_range": None,
            "times": first.times,
            "last_check_time": None,
            "next_run_time": None,
            "interval": None,
            "is_enabled": True,
            "run_status": "queued",
            "business_pk": seeded_schedule_context["business"].id,
            "naver_biz_item_id": item.biz_item_id,
            "business_name": seeded_schedule_context["business"].name,
            "naver_business_id": seeded_schedule_context["business"].business_id,
        }
    )
    worker._store_active_schedule(
        {
            "id": second.id,
            "biz_item_id": item.id,
            "service_account_id": account.id,
            "date": second.date,
            "time_range": None,
            "times": second.times,
            "last_check_time": None,
            "next_run_time": None,
            "interval": None,
            "is_enabled": True,
            "run_status": "queued",
            "business_pk": seeded_schedule_context["business"].id,
            "naver_biz_item_id": item.biz_item_id,
            "business_name": seeded_schedule_context["business"].name,
            "naver_business_id": seeded_schedule_context["business"].business_id,
        }
    )

    run_group_key = f"{item.id}:2026-04-27"
    assert list(worker._run_groups.keys()) == [run_group_key]
    assert worker._active_schedules[first.id]["run_group_size"] == 2
    assert worker._active_schedules[second.id]["run_group_size"] == 2

    selected_ids = [
        worker._select_next_schedule_for_group(run_group_key)["id"]
        for _ in range(4)
    ]
    assert selected_ids == [first.id, second.id, first.id, second.id]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_startup_pending_rows_promote_to_queued_and_dispatch_round_robin(
    test_db_session,
    seeded_schedule_context,
):
    item = seeded_schedule_context["item"]
    account = seeded_schedule_context["account"]

    first = MonitorSchedule(
        biz_item_id=item.id,
        service_account_id=None,
        date="2026-04-28",
        times="[\"09:00\"]",
        is_enabled=True,
        run_status="pending",
    )
    second = MonitorSchedule(
        biz_item_id=item.id,
        service_account_id=account.id,
        date="2026-04-28",
        times="[\"11:00\"]",
        is_enabled=True,
        run_status="pending",
    )
    test_db_session.add_all([first, second])
    test_db_session.commit()
    test_db_session.refresh(first)
    test_db_session.refresh(second)

    worker = NaverMonitorWorker()
    with patch.object(test_db_session, "close", return_value=None), patch(
        "app.worker.naver_monitor_worker.SessionLocal",
        return_value=test_db_session,
    ):
        await worker._load_active_schedules()

    test_db_session.refresh(first)
    test_db_session.refresh(second)
    assert first.run_status == "queued"
    assert second.run_status == "queued"
    assert first.next_run_time is not None
    assert second.next_run_time is not None

    target_group_key = f"{item.id}:2026-04-28"
    worker._run_groups = {
        target_group_key: worker._run_groups[target_group_key]
    }
    worker._active_schedules = {
        first.id: worker._active_schedules[first.id],
        second.id: worker._active_schedules[second.id],
    }

    dispatched = []

    async def fake_check(schedule_meta):
        dispatched.append(schedule_meta["id"])
        worker._active_schedules[schedule_meta["id"]]["next_run_time"] = datetime.now() + timedelta(seconds=60)

    worker._check_schedule = AsyncMock(side_effect=fake_check)

    await worker._dispatch_due_monitoring_schedules()
    await worker._dispatch_due_monitoring_schedules()

    assert dispatched == [first.id, second.id]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pending_schedule_consumed_after_worker_restart(
    test_db_session,
    seeded_schedule_context,
):
    item = seeded_schedule_context["item"]

    schedule = MonitorSchedule(
        biz_item_id=item.id,
        service_account_id=None,
        date="2026-04-30",
        times="[\"10:00\"]",
        is_enabled=True,
        run_status="pending",
        next_run_time=None,
    )
    test_db_session.add(schedule)
    test_db_session.commit()
    test_db_session.refresh(schedule)

    worker = NaverMonitorWorker()
    with patch.object(test_db_session, "close", return_value=None), patch(
        "app.worker.naver_monitor_worker.SessionLocal",
        return_value=test_db_session,
    ):
        await worker._load_active_schedules()

    target_group_key = f"{item.id}:2026-04-30"
    worker._run_groups = {
        target_group_key: worker._run_groups[target_group_key]
    }
    worker._active_schedules = {
        schedule.id: worker._active_schedules[schedule.id]
    }

    dispatched = []

    async def fake_check(schedule_meta):
        dispatched.append(schedule_meta["id"])
        worker._active_schedules[schedule_meta["id"]]["next_run_time"] = datetime.now() + timedelta(seconds=30)

    worker._check_schedule = AsyncMock(side_effect=fake_check)
    await worker._dispatch_due_monitoring_schedules()

    assert dispatched == [schedule.id]
    assert worker._active_schedules[schedule.id]["run_status"] == "queued"
    assert worker._active_schedules[schedule.id]["next_run_time"] is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_check_schedule_persists_last_check_and_next_run_time_after_startup_promotion(
    test_db_session,
    seeded_schedule_context,
):
    item = seeded_schedule_context["item"]

    schedule = MonitorSchedule(
        biz_item_id=item.id,
        service_account_id=None,
        date="2026-04-29",
        times="[\"13:00\"]",
        is_enabled=True,
        run_status="pending",
    )
    test_db_session.add(schedule)
    test_db_session.commit()
    test_db_session.refresh(schedule)

    worker = NaverMonitorWorker()
    with patch.object(test_db_session, "close", return_value=None), patch(
        "app.worker.naver_monitor_worker.SessionLocal",
        return_value=test_db_session,
    ):
        await worker._load_active_schedules()

        checked_at = datetime.now()
        next_run_time = checked_at + timedelta(seconds=45)
        worker._execute_monitoring_cycle = AsyncMock(return_value={
            "checked_at": checked_at,
            "next_run_time": next_run_time,
            "event_status": "no_slots",
            "last_slots": [],
            "last_data_hash": "hash-after-check",
            "error_message": None,
        })

        await worker._check_schedule(worker._active_schedules[schedule.id])

    test_db_session.refresh(schedule)
    assert schedule.run_status == "queued"
    assert schedule.last_check_time == checked_at
    assert schedule.next_run_time == next_run_time
    assert worker._active_schedules[schedule.id]["last_check_time"] == checked_at
    assert worker._active_schedules[schedule.id]["next_run_time"] == next_run_time


# ============================================================
# T3: 과거 날짜 필터 PG 통합 케이스
# ============================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_past_date_excluded_from_startup_load(test_db_session, seeded_schedule_context):
    """[T3-28] _load_active_schedules가 PG에서 과거 날짜 row를 제외하고 오늘/미래만 로드한다."""
    item = seeded_schedule_context["item"]
    today = "2026-04-22"
    past = "2026-04-21"
    future = "2026-04-29"

    past_sched = MonitorSchedule(
        biz_item_id=item.id, service_account_id=None,
        date=past, times='["10:00"]', is_enabled=True, run_status="queued",
    )
    today_sched = MonitorSchedule(
        biz_item_id=item.id, service_account_id=None,
        date=today, times='["11:00"]', is_enabled=True, run_status="queued",
    )
    future_sched = MonitorSchedule(
        biz_item_id=item.id, service_account_id=None,
        date=future, times='["12:00"]', is_enabled=True, run_status="queued",
    )
    test_db_session.add_all([past_sched, today_sched, future_sched])
    test_db_session.commit()
    for s in [past_sched, today_sched, future_sched]:
        test_db_session.refresh(s)

    worker = NaverMonitorWorker()
    with patch.object(test_db_session, "close", return_value=None), \
         patch("app.worker.naver_monitor_worker.SessionLocal", return_value=test_db_session), \
         patch.object(NaverMonitorWorker, "_get_today_kst", return_value=today):
        await worker._load_active_schedules()

    assert past_sched.id not in worker._active_schedules
    assert today_sched.id in worker._active_schedules
    assert future_sched.id in worker._active_schedules


@pytest.mark.integration
@pytest.mark.asyncio
async def test_past_pending_not_queued_by_check_for_new_schedules(test_db_session, seeded_schedule_context):
    """[T3-29] _check_for_new_schedules가 PG에서 과거 pending row를 queued로 승격하지 않는다."""
    item = seeded_schedule_context["item"]
    today = "2026-04-22"
    past = "2026-04-21"

    past_pending = MonitorSchedule(
        biz_item_id=item.id, service_account_id=None,
        date=past, times='["10:00"]', is_enabled=True, run_status="pending",
    )
    today_pending = MonitorSchedule(
        biz_item_id=item.id, service_account_id=None,
        date=today, times='["11:00"]', is_enabled=True, run_status="pending",
    )
    test_db_session.add_all([past_pending, today_pending])
    test_db_session.commit()
    for s in [past_pending, today_pending]:
        test_db_session.refresh(s)

    worker = NaverMonitorWorker()
    with patch.object(test_db_session, "close", return_value=None), \
         patch("app.worker.naver_monitor_worker.SessionLocal", return_value=test_db_session), \
         patch.object(NaverMonitorWorker, "_get_today_kst", return_value=today):
        await worker._check_for_new_schedules()

    test_db_session.refresh(past_pending)
    test_db_session.refresh(today_pending)

    # 과거 row는 queued 미승격
    assert past_pending.run_status == "pending"
    assert past_pending.id not in worker._active_schedules
    # 오늘 row는 queued 승격
    assert today_pending.run_status == "queued"
    assert today_pending.id in worker._active_schedules


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stale_row_pruned_before_dispatch(test_db_session, seeded_schedule_context):
    """[T3-30] startup 때 오늘이었던 row가 cutoff를 넘기면 dispatch 전 prune으로 제거된다."""
    item = seeded_schedule_context["item"]
    stale_date = "2026-04-21"  # prune 시점에는 '어제'

    schedule = MonitorSchedule(
        biz_item_id=item.id, service_account_id=None,
        date=stale_date, times='["10:00"]', is_enabled=True, run_status="queued",
    )
    test_db_session.add(schedule)
    test_db_session.commit()
    test_db_session.refresh(schedule)

    worker = NaverMonitorWorker()
    # 먼저 stale_date가 오늘인 것처럼 startup load
    with patch.object(test_db_session, "close", return_value=None), \
         patch("app.worker.naver_monitor_worker.SessionLocal", return_value=test_db_session), \
         patch.object(NaverMonitorWorker, "_get_today_kst", return_value=stale_date):
        await worker._load_active_schedules()

    assert schedule.id in worker._active_schedules

    # 격리: 다른 테스트의 row 제거, 대상 schedule만 남김
    worker._active_schedules = {schedule.id: worker._active_schedules[schedule.id]}
    worker._run_groups = {k: v for k, v in worker._run_groups.items()
                         if schedule.id in v.get("schedule_ids", [])}

    # 이제 오늘이 다음 날로 넘어감 → prune이 실행되어야 함
    check_calls = []

    async def fake_check(meta):
        check_calls.append(meta["id"])

    worker._check_schedule = AsyncMock(side_effect=fake_check)

    with patch.object(NaverMonitorWorker, "_get_today_kst", return_value="2026-04-22"):
        await worker._dispatch_due_monitoring_schedules()

    # prune이 stale row를 제거하여 check_schedule이 호출되지 않음
    assert schedule.id not in worker._active_schedules
    assert schedule.id not in check_calls

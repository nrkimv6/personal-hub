"""Same-date monitor schedule integration tests.

Phase T3 focuses on the post-migration contract:
- same biz_item/date rows can be stored multiple times
- NULL/non-NULL service_account rows can coexist
- worker run-group metadata dedupes by biz_item/date and rotates
"""

import uuid

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
def test_pending_schedule_consumed_after_worker_restart(test_db_session, seeded_schedule_context):
    """
    [T3] worker restart 후 pending 스케줄이 _run_monitoring_checks()에서 실행 대상으로 선택됨.

    근본 원인 재현: _main_loop_iteration()에 _run_monitoring_checks() 호출이 없어
    _active_schedules에 pending 스케줄 284개가 있어도 실행 코드가 없어 정체됨.
    수정 후: _run_monitoring_checks()가 next_run_time=None 스케줄을 즉시 실행 대상으로
    선택해 _check_schedule()를 호출함을 실제 DB + 실 워커 인스턴스로 검증.
    """
    import asyncio
    from unittest.mock import patch, MagicMock

    item = seeded_schedule_context["item"]
    business = seeded_schedule_context["business"]

    # 1. pending 스케줄 직접 삽입 (실제 PostgreSQL, next_run_time=None → 즉시 실행 대상)
    schedule = MonitorSchedule(
        biz_item_id=item.id,
        date="2026-04-20",
        times='["10:00"]',
        is_enabled=True,
        run_status="pending",
        next_run_time=None,
    )
    test_db_session.add(schedule)
    test_db_session.commit()
    test_db_session.refresh(schedule)
    schedule_id = schedule.id

    # 2. worker 생성 + startup 시 pending 스케줄 로드 시뮬레이션 (_store_active_schedule)
    worker = NaverMonitorWorker()
    worker._store_active_schedule({
        "id": schedule_id,
        "biz_item_id": item.id,
        "service_account_id": None,
        "date": "2026-04-20",
        "time_range": None,
        "times": '["10:00"]',
        "last_check_time": None,
        "next_run_time": None,
        "interval": 30,
        "is_enabled": True,
        "run_status": "pending",
        "business_pk": business.id,
        "naver_biz_item_id": item.biz_item_id,
        "business_name": business.name,
        "naver_business_id": business.business_id,
    })
    assert schedule_id in worker._active_schedules, "사전조건: startup 로드 후 스케줄이 active에 있어야 함"

    # 3. fresh context (schedule_service.get_all_with_context 반환값)
    fresh_ctx = {
        "id": schedule_id,
        "biz_item_id": item.id,
        "business_type_id": business.business_type_id,
        "business_id": business.business_id,
        "item_biz_item_id": item.biz_item_id,
        "date": "2026-04-20",
        "times": '["10:00"]',
        "next_run_time": None,
        "interval": 30,
        "is_enabled": True,
        "run_status": "pending",
    }

    # 4. _check_schedule 호출 캡처 (AnonymousMonitor 등 외부 의존성 차단)
    check_called_ids: list = []

    async def capture_check_schedule(ctx: dict) -> None:
        check_called_ids.append(ctx["id"])

    worker._check_schedule = capture_check_schedule  # type: ignore[method-assign]

    mock_db = MagicMock()
    with patch("app.worker.naver_monitor_worker.SessionLocal", return_value=mock_db), \
         patch("app.worker.naver_monitor_worker.schedule_service") as mock_svc:
        mock_svc.get_all_with_context.return_value = [fresh_ctx]
        asyncio.run(worker._run_monitoring_checks())

    # 5. 검증: pending 스케줄이 _check_schedule 호출 대상이 됨 — 실행 루프 수정 확인
    assert schedule_id in check_called_ids, (
        f"schedule_id={schedule_id} (pending, next_run_time=None)이 _run_monitoring_checks()에서 "
        f"_check_schedule() 대상으로 선택되어야 함 — 실행 루프 누락 회귀 방지"
    )

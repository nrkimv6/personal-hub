"""Phase T4 mock E2E for same-date schedule dedupe/rotation."""

from unittest.mock import MagicMock, patch

import pytest

from app.worker.naver_monitor_worker import NaverMonitorWorker


def _pending_row(
    schedule_id: int,
    biz_item_id: int,
    service_account_id: int | None,
    date: str,
    times: str,
):
    return (
        schedule_id,
        biz_item_id,
        service_account_id,
        date,
        None,
        times,
        None,
        None,
        60,
        True,
        "pending",
        10,
        f"naver-item-{biz_item_id}",
        "Biz",
        "biz-1",
    )


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_same_date_rows_load_into_one_group_and_rotate():
    worker = NaverMonitorWorker()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        _pending_row(1, 100, 1, "2026-04-30", '["10:00"]'),
        _pending_row(2, 100, 2, "2026-04-30", '["14:00"]'),
    ]

    with patch("app.worker.naver_monitor_worker.SessionLocal") as mock_session_local:
        mock_db = MagicMock()
        mock_db.execute.return_value = mock_result
        mock_session_local.return_value = mock_db

        await worker._check_for_new_schedules()

    assert list(worker._run_groups.keys()) == ["100:2026-04-30"]
    assert worker._run_groups["100:2026-04-30"]["schedule_ids"] == [1, 2]
    assert [
        worker._select_next_schedule_for_group("100:2026-04-30")["id"]
        for _ in range(4)
    ] == [1, 2, 1, 2]


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_new_same_date_row_is_joined_to_existing_group():
    worker = NaverMonitorWorker()
    worker._store_active_schedule(
        {
            "id": 1,
            "biz_item_id": 100,
            "service_account_id": 1,
            "date": "2026-05-01",
            "time_range": None,
            "times": '["10:00"]',
            "last_check_time": None,
            "next_run_time": None,
            "interval": 60,
            "is_enabled": True,
            "run_status": "queued",
            "business_pk": 10,
            "naver_biz_item_id": "naver-item-100",
            "business_name": "Biz",
            "naver_business_id": "biz-1",
        }
    )

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        _pending_row(2, 100, 2, "2026-05-01", '["14:00"]'),
    ]

    with patch("app.worker.naver_monitor_worker.SessionLocal") as mock_session_local:
        mock_db = MagicMock()
        mock_db.execute.return_value = mock_result
        mock_session_local.return_value = mock_db

        await worker._check_for_new_schedules()

    group = worker._run_groups["100:2026-05-01"]
    assert group["schedule_ids"] == [1, 2]
    assert worker._active_schedules[1]["run_group_size"] == 2
    assert worker._active_schedules[2]["run_group_size"] == 2


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_disabled_row_shrinks_group_and_updates_next_selection():
    worker = NaverMonitorWorker()
    worker._store_active_schedule(
        {
            "id": 1,
            "biz_item_id": 100,
            "service_account_id": 1,
            "date": "2026-05-02",
            "time_range": None,
            "times": '["10:00"]',
            "last_check_time": None,
            "next_run_time": None,
            "interval": 60,
            "is_enabled": True,
            "run_status": "queued",
            "business_pk": 10,
            "naver_biz_item_id": "naver-item-100",
            "business_name": "Biz",
            "naver_business_id": "biz-1",
        }
    )
    worker._store_active_schedule(
        {
            "id": 2,
            "biz_item_id": 100,
            "service_account_id": 2,
            "date": "2026-05-02",
            "time_range": None,
            "times": '["14:00"]',
            "last_check_time": None,
            "next_run_time": None,
            "interval": 60,
            "is_enabled": True,
            "run_status": "queued",
            "business_pk": 10,
            "naver_biz_item_id": "naver-item-100",
            "business_name": "Biz",
            "naver_business_id": "biz-1",
        }
    )

    first_selected = worker._select_next_schedule_for_group("100:2026-05-02")
    assert first_selected["id"] == 1

    disabled_result = MagicMock()
    disabled_result.fetchall.return_value = [(1,)]

    with patch("app.worker.naver_monitor_worker.SessionLocal") as mock_session_local:
        mock_db = MagicMock()
        mock_db.execute.return_value = disabled_result
        mock_session_local.return_value = mock_db

        await worker._check_for_disabled_schedules()

    assert worker._run_groups["100:2026-05-02"]["schedule_ids"] == [2]
    assert worker._select_next_schedule_for_group("100:2026-05-02")["id"] == 2

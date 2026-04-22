"""Phase T4 mock E2E for same-date schedule dedupe/rotation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker.naver_monitor_worker import NaverMonitorWorker
from app.shared.worker.exceptions import TabOperationTimeout


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


def _make_schedule_meta(schedule_id: int = 199) -> dict:
    return {
        "id": schedule_id,
        "biz_item_id": 100,
        "service_account_id": 1,
        "date": "2026-04-22",
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
        "error_count": 0,
        "last_error": None,
        "last_slots": None,
        "last_data_hash": None,
    }


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_due_schedule_timeout_is_reported_with_stage_acquire():
    """overdue schedule TabOperationTimeout(stage=acquire) 시 last_error에 stage=acquire가 기록되고 worker loop가 유지되는지 검증"""
    worker = NaverMonitorWorker()
    meta = _make_schedule_meta(199)
    worker._store_active_schedule(meta)

    timeout_err = TabOperationTimeout("탭 획득 타임아웃 (stage=acquire)", timeout=60.0)

    with patch("app.worker.naver_monitor_worker.SessionLocal") as mock_sl, \
         patch("app.worker.naver_monitor_worker.EventLogger"), \
         patch.object(worker, "_execute_monitoring_cycle", side_effect=timeout_err):
        mock_db = MagicMock()
        mock_sl.return_value = mock_db
        mock_db.execute.return_value = MagicMock()

        with pytest.raises(TabOperationTimeout):
            await worker._check_schedule(meta)

    stored = worker._active_schedules.get(199)
    assert stored is not None, "schedule이 active_schedules에서 사라짐 (loop 유지 실패)"
    last_error = stored.get("last_error", "")
    assert last_error is not None, "last_error가 None"
    assert "stage=acquire" in last_error, f"last_error에 stage=acquire 없음: {last_error!r}"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_due_schedule_retries_after_acquire_timeout_without_waiter_leak():
    """동일 schedule 2회 연속 TabOperationTimeout 처리 후 active_schedule / run-group이 유지되고 error_count가 누적되는지 검증"""
    worker = NaverMonitorWorker()
    meta = _make_schedule_meta(199)
    worker._store_active_schedule(meta)

    timeout_err = TabOperationTimeout("탭 획득 타임아웃 (stage=acquire)", timeout=60.0)

    with patch("app.worker.naver_monitor_worker.SessionLocal") as mock_sl, \
         patch("app.worker.naver_monitor_worker.EventLogger"), \
         patch.object(worker, "_execute_monitoring_cycle", side_effect=timeout_err):
        mock_db = MagicMock()
        mock_sl.return_value = mock_db
        mock_db.execute.return_value = MagicMock()

        for _ in range(2):
            with pytest.raises(TabOperationTimeout):
                await worker._check_schedule(meta)

    assert 199 in worker._active_schedules, "schedule이 active_schedules에서 제거됨"
    stored = worker._active_schedules[199]
    group_key = f"{stored.get('biz_item_id')}:{stored.get('date')}"
    assert group_key in worker._run_groups, f"run_group {group_key!r} 제거됨"
    assert stored.get("error_count", 0) >= 2, f"error_count 누적 실패: {stored.get('error_count')}"


# ============================================================
# Phase T4: 과거 날짜 필터 E2E (merge-test 후 실행)
# ============================================================

def _startup_row_with_date(
    schedule_id: int,
    biz_item_id: int,
    date: str,
    run_status: str = "queued",
):
    return (
        schedule_id,
        biz_item_id,
        60,
        True,
        1,
        run_status,
        date,
        None,
        '["10:00"]',
        None,
        None,
        biz_item_id,
        f"nitem-{schedule_id}",
        "Biz",
        f"biz-{biz_item_id}",
    )


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_startup_load_excludes_past_date_rows_right():
    """startup load에서 과거 row가 group에 올라가지 않는다 — DB가 필터링한 결과만 active에 진입."""
    worker = NaverMonitorWorker()
    today = "2026-04-22"

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        _startup_row_with_date(10, 200, today),
        _startup_row_with_date(11, 201, "2099-12-31"),
    ]

    execute_params = []

    def capture(query, params=None):
        execute_params.append(params or {})
        return mock_result

    with patch("app.worker.naver_monitor_worker.SessionLocal") as mock_sl, \
         patch.object(worker.__class__, "_get_today_kst", return_value=today):
        mock_db = MagicMock()
        mock_db.execute.side_effect = capture
        mock_sl.return_value = mock_db

        await worker._load_active_schedules()

    # today_kst 파라미터가 SQL에 전달됨
    assert any("today_kst" in p for p in execute_params), "today_kst 파라미터가 SQL에 전달되지 않음"
    # DB 반환값(필터 통과분)만 active에 존재
    assert 10 in worker._active_schedules
    assert 11 in worker._active_schedules
    # 과거 날짜 row는 DB 필터에서 제외되어 반환 자체가 없음 — active에 없어야 함
    assert 9 not in worker._active_schedules, "과거 row(id=9)가 active에 올라갔음"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_pending_poll_excludes_past_date_rows_right():
    """pending poll에서 과거 row가 queued로 승격되지 않는다 — DB가 필터링한 결과만 active에 진입."""
    worker = NaverMonitorWorker()
    today = "2026-04-22"

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        _pending_row(20, 200, 1, today, '["10:00"]'),
    ]

    execute_params = []

    def capture(query, params=None):
        execute_params.append(params or {})
        return mock_result

    with patch("app.worker.naver_monitor_worker.SessionLocal") as mock_sl, \
         patch.object(worker.__class__, "_get_today_kst", return_value=today):
        mock_db = MagicMock()
        mock_db.execute.side_effect = capture
        mock_sl.return_value = mock_db

        await worker._check_for_new_schedules()

    assert any("today_kst" in p for p in execute_params), "today_kst 파라미터가 SQL에 전달되지 않음"
    assert 20 in worker._active_schedules
    assert worker._active_schedules[20]["run_status"] == "queued"
    # 과거 row(id=19)는 DB 단에서 제외됨 — mock이 반환하지 않으므로 active에 없음
    assert 19 not in worker._active_schedules, "과거 row(id=19)가 active에 올라갔음"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_stale_prune_removes_past_rows_before_dispatch_right():
    """stale prune이 dispatch 전 과거 row를 active/run_group에서 제거한다."""
    worker = NaverMonitorWorker()
    today = "2026-04-22"
    past = "2026-04-21"

    worker._store_active_schedule({
        "id": 30, "biz_item_id": 300, "service_account_id": 1,
        "date": past, "time_range": None, "times": '["10:00"]',
        "last_check_time": None, "next_run_time": None,
        "interval": 60, "is_enabled": True, "run_status": "queued",
        "business_pk": 10, "naver_biz_item_id": "item-30",
        "business_name": "Biz", "naver_business_id": "biz-300",
    })
    assert 30 in worker._active_schedules

    with patch.object(worker.__class__, "_get_today_kst", return_value=today):
        pruned = worker._prune_past_active_schedules()

    assert pruned == 1, f"prune 결과가 1이어야 함: {pruned}"
    assert 30 not in worker._active_schedules, "과거 row(id=30)가 prune 후에도 active에 남아있음"
    assert "300:2026-04-21" not in worker._run_groups

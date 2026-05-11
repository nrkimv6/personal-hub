"""NaverMonitorCycleRunner 단위 TC (RIGHT-BICEP).

event status/hash assertions are fetch-cycle outputs, not MonitorSchedule.run_status transitions.
"""
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker.naver_monitor_cycle import NaverMonitorCycleRunner
from app.modules.naver_booking.services.site_monitor import FetchResult


# ---- 헬퍼 ----

def _make_runner(site_monitor=None, browser=None):
    mock_sm = site_monitor or MagicMock()
    mock_bm = browser or MagicMock()
    return NaverMonitorCycleRunner(site_monitor=mock_sm, browser_manager=mock_bm)


def _make_schedule(monitoring_mode="anonymous", **kwargs):
    base = {
        "id": 1,
        "url": "https://example.com",
        "date": "2026-04-25",
        "naver_business_id": "biz1",
        "naver_biz_item_id": "item1",
        "biz_item_id": "item1",
        "business_name": "TestBiz",
        "monitoring_mode": monitoring_mode,
        "source_type": "manual",
        "business_type_id": 13,
        "last_slots": [],
        "last_data_hash": None,
        "time_range": None,
        "times": None,
        "interval": 60,
        "service_account_id": None,
    }
    base.update(kwargs)
    return base


# ---- Phase T1: execute_monitoring_cycle ----

@pytest.mark.asyncio
async def test_execute_monitoring_cycle_anonymous_right():
    """R: monitoring_mode=anonymous → _run_anonymous_cycle 호출, execute_with_tab 미호출."""
    runner = _make_runner()
    schedule = _make_schedule(monitoring_mode="anonymous")

    anon_result = FetchResult(hash=123, slots=["10:00 (2매)"], status="available")
    with patch.object(runner, "_run_anonymous_cycle", new=AsyncMock(return_value=anon_result)):
        with patch("app.worker.naver_monitor_cycle.EventLogger") as mock_el:
            mock_el.log_monitoring_event = MagicMock()
            result = await runner.execute_monitoring_cycle(schedule)

    assert result["event_status"] == "available"
    runner._browser.execute_with_tab.assert_not_called()


@pytest.mark.asyncio
async def test_execute_monitoring_cycle_legacy_right():
    """R: monitoring_mode=legacy → browser.execute_with_tab 호출, _run_anonymous_cycle 미호출."""
    mock_browser = MagicMock()
    fetch_result = FetchResult(hash=456, slots=[], status="no_slots")
    mock_browser.execute_with_tab = AsyncMock(return_value=fetch_result)

    mock_sm = MagicMock()
    mock_sm.perform_task_with_fetch = AsyncMock(return_value=fetch_result)

    runner = _make_runner(site_monitor=mock_sm, browser=mock_browser)
    schedule = _make_schedule(monitoring_mode="legacy")

    with patch.object(runner, "_run_anonymous_cycle", new=AsyncMock()) as mock_anon:
        with patch("app.worker.naver_monitor_cycle.EventLogger") as mock_el:
            mock_el.log_monitoring_event = MagicMock()
            result = await runner.execute_monitoring_cycle(schedule)

    mock_anon.assert_not_called()
    mock_browser.execute_with_tab.assert_called_once()
    assert result["event_status"] == "no_slots"


@pytest.mark.asyncio
async def test_execute_monitoring_cycle_null_mode_fallback():
    """B: monitoring_mode=None → coerce_monitoring_mode → anonymous 경로."""
    runner = _make_runner()
    schedule = _make_schedule(monitoring_mode=None)

    anon_result = FetchResult(hash=0, slots=[], status="no_slots")
    with patch.object(runner, "_run_anonymous_cycle", new=AsyncMock(return_value=anon_result)) as mock_anon:
        with patch("app.worker.naver_monitor_cycle.EventLogger") as mock_el:
            mock_el.log_monitoring_event = MagicMock()
            await runner.execute_monitoring_cycle(schedule)

    mock_anon.assert_called_once()


@pytest.mark.asyncio
async def test_execute_monitoring_cycle_no_site_monitor_error():
    """E: _site_monitor=None → RuntimeError 발생."""
    runner = NaverMonitorCycleRunner(site_monitor=None, browser_manager=MagicMock())
    schedule = _make_schedule()
    with pytest.raises(RuntimeError, match="NaverSiteMonitor"):
        await runner.execute_monitoring_cycle(schedule)


@pytest.mark.asyncio
async def test_execute_monitoring_cycle_no_browser_legacy_error():
    """E: legacy mode + browser=None → RuntimeError 발생."""
    runner = NaverMonitorCycleRunner(site_monitor=MagicMock(), browser_manager=None)
    schedule = _make_schedule(monitoring_mode="legacy")
    with pytest.raises(RuntimeError, match="BrowserManager"):
        await runner.execute_monitoring_cycle(schedule)


# ---- Phase T1: _run_anonymous_cycle ----

@pytest.mark.asyncio
async def test_run_anonymous_cycle_available():
    """R: get_anonymous_monitor mock → available 슬롯 → FetchResult(status="available")."""
    runner = _make_runner()
    schedule = _make_schedule()

    mock_slot = MagicMock()
    mock_slot.start_time = "10:00"
    mock_slot.unit_stock = 5
    mock_slot.unit_booking_count = 2

    mock_avail = MagicMock()
    mock_avail.error = None
    mock_avail.slots = [mock_slot]

    mock_anon = MagicMock()
    mock_anon.check_availability = AsyncMock(return_value=mock_avail)

    with patch("app.worker.naver_monitor_cycle.NaverMonitorCycleRunner._run_anonymous_cycle",
               new=AsyncMock(return_value=None)):
        pass  # 직접 호출하는 방식으로 테스트

    with patch("app.modules.naver_booking.services.anonymous_monitor.get_anonymous_monitor",
               return_value=mock_anon):
        result = await runner._run_anonymous_cycle(schedule, current_hash=0, current_slots=[])

    assert result.status == "available"
    assert "10:00 (3매)" in result.slots


@pytest.mark.asyncio
async def test_run_anonymous_cycle_no_slots():
    """B: 슬롯 없음 → FetchResult(status="no_slots")."""
    runner = _make_runner()
    schedule = _make_schedule()

    mock_avail = MagicMock()
    mock_avail.error = None
    mock_avail.slots = []

    mock_anon = MagicMock()
    mock_anon.check_availability = AsyncMock(return_value=mock_avail)

    with patch("app.modules.naver_booking.services.anonymous_monitor.get_anonymous_monitor",
               return_value=mock_anon):
        result = await runner._run_anonymous_cycle(schedule, current_hash=0, current_slots=[])

    assert result.status == "no_slots"


@pytest.mark.asyncio
async def test_run_anonymous_cycle_error():
    """E: availability.error 반환 → FetchResult(status="error", reason=...)."""
    runner = _make_runner()
    schedule = _make_schedule()

    mock_avail = MagicMock()
    mock_avail.error = "network failure"
    mock_avail.slots = []

    mock_anon = MagicMock()
    mock_anon.check_availability = AsyncMock(return_value=mock_avail)

    with patch("app.modules.naver_booking.services.anonymous_monitor.get_anonymous_monitor",
               return_value=mock_anon):
        result = await runner._run_anonymous_cycle(schedule, current_hash=99, current_slots=["slot1"])

    assert result.status == "error"
    assert result.reason == "network failure"
    assert result.hash == 99


# ---- Phase T1: _adapt_anonymous_result ----

def test_adapt_anonymous_result_slot_format():
    """R: slot start_time+unit_stock/unit_booking_count → 포맷 '{start_time} ({n}매)'."""
    runner = _make_runner()

    mock_slot = MagicMock()
    mock_slot.start_time = "14:30"
    mock_slot.unit_stock = 10
    mock_slot.unit_booking_count = 3

    mock_avail = MagicMock()
    mock_avail.error = None
    mock_avail.slots = [mock_slot]

    result = runner._adapt_anonymous_result(mock_avail, current_hash=0, current_slots=[])

    assert result.status == "available"
    assert result.slots == ["14:30 (7매)"]


# ---- Phase T1: _calculate_next_run_time ----

def test_calculate_next_run_time_interval_used():
    """R: interval=120 → checked_at + timedelta(seconds=120)."""
    schedule = _make_schedule(interval=120)
    checked_at = datetime(2026, 4, 25, 12, 0, 0)
    result = NaverMonitorCycleRunner._calculate_next_run_time(schedule, checked_at)
    assert result == checked_at + timedelta(seconds=120)


def test_calculate_next_run_time_default_fallback():
    """B: interval=None → calculate_default_interval(date) 호출 경로."""
    schedule = _make_schedule(interval=None, date="2026-04-25")
    checked_at = datetime(2026, 4, 25, 12, 0, 0)

    with patch("app.worker.naver_monitor_cycle.calculate_default_interval", return_value=300) as mock_cdi:
        result = NaverMonitorCycleRunner._calculate_next_run_time(schedule, checked_at)

    mock_cdi.assert_called_once_with("2026-04-25")
    assert result == checked_at + timedelta(seconds=300)


# ---- Phase T1: _deserialize_schedule_times ----

def test_deserialize_schedule_times_json_list():
    """R: '["10:00","11:00"]' → ["10:00","11:00"]."""
    result = NaverMonitorCycleRunner._deserialize_schedule_times('["10:00","11:00"]')
    assert result == ["10:00", "11:00"]


def test_deserialize_schedule_times_none():
    """B: None → []."""
    result = NaverMonitorCycleRunner._deserialize_schedule_times(None)
    assert result == []


def test_deserialize_schedule_times_plain_list():
    """R: list 입력 → str 변환 후 반환."""
    result = NaverMonitorCycleRunner._deserialize_schedule_times(["10:00", "11:00"])
    assert result == ["10:00", "11:00"]


def test_deserialize_schedule_times_plain_string():
    """B: JSON 아닌 plain string → 단일 원소 list."""
    result = NaverMonitorCycleRunner._deserialize_schedule_times("10:00")
    assert result == ["10:00"]

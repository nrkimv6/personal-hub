"""
T3 통합 TC: NaverMonitorWorker monitoring_mode 라우팅 재현

근본 원인: _execute_monitoring_cycle이 monitoring_mode를 무시하고 항상 execute_with_tab 호출.
축 분류: anonymous/legacy routing은 상태 display/override 축이 아니라 fetch path integration 축이다.
수정 후 계약 검증 (T1 단위테스트보다 실제 코드 경로 더 많이 사용):
1. anonymous 모드 → 실제 _run_anonymous_cycle 경로 실행, get_anonymous_monitor 호출 검증
2. legacy 모드 → execute_with_tab 호출, check_availability 미호출
3. anonymous 모드 EventLogger → fetch_method='anonymous_api' 전파 검증
4. adapter 슬롯 포맷 → site_monitor.py:1000 legacy 포맷과 동일
5. adapter 포맷 정합성 — fixture 응답 기반

실행:
    python -m pytest tests/integration/test_naver_monitor_mode_routing.py -v
"""
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import re
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_schedule_meta(monitoring_mode="anonymous"):
    return {
        "id": 9900,
        "monitoring_mode": monitoring_mode,
        "naver_business_id": "biz-T3-001",
        "naver_biz_item_id": "item-T3-001",
        "biz_item_id": 1,
        "business_type_id": 13,
        "date": "2026-04-25",
        "url": "https://booking.naver.com/booking/5/bizes/1/items/1?startDate=2026-04-25",
        "business_name": "T3 Biz",
        "interval": 60.0,
        "service_account_id": None,
        "last_slots": None,
        "last_data_hash": None,
    }


def _make_anon_availability(*, error=None, slots=None):
    a = MagicMock()
    a.error = error
    a.slots = slots or []
    a.available = bool(slots)
    return a


def _make_slot(start_time, unit_stock, unit_booking_count):
    s = MagicMock()
    s.start_time = start_time
    s.unit_stock = unit_stock
    s.unit_booking_count = unit_booking_count
    return s


class TestAnonymousScheduleRoutesIntegration:
    """
    anonymous 모드: 실제 _run_anonymous_cycle 경로 실행.
    T1과 달리 _run_anonymous_cycle을 직접 mock하지 않고
    get_anonymous_monitor 경계에서만 patch한다.
    """

    @pytest.mark.asyncio
    async def test_anonymous_schedule_routes_to_anonymous_monitor(self):
        """
        T3: anonymous 모드 → 실제 _run_anonymous_cycle → get_anonymous_monitor().check_availability 호출.
        execute_with_tab 미호출.

        T1과의 차이: _run_anonymous_cycle을 mock하지 않고 실제 실행 — 체인 전체를 통과.
        """
        from app.worker.naver_monitor_worker import NaverMonitorWorker
        from app.worker.naver_monitor_cycle import NaverMonitorCycleRunner

        worker = NaverMonitorWorker()
        worker._site_monitor = MagicMock()
        worker.browser = MagicMock()
        worker.browser.execute_with_tab = AsyncMock()
        worker._cycle_runner = NaverMonitorCycleRunner(
            site_monitor=worker._site_monitor, browser_manager=worker.browser
        )

        mock_availability = _make_anon_availability(slots=[])
        mock_anon = MagicMock()
        mock_anon.check_availability = AsyncMock(return_value=mock_availability)

        schedule_meta = _make_schedule_meta(monitoring_mode="anonymous")

        with patch(
            "app.modules.naver_booking.services.anonymous_monitor.get_anonymous_monitor",
            return_value=mock_anon,
        ):
            with patch("app.services.event_logger.EventLogger.log_monitoring_event"):
                await worker._execute_monitoring_cycle(schedule_meta)

        # get_anonymous_monitor 경계에서 1회 호출 확인
        mock_anon.check_availability.assert_awaited_once()
        call_kwargs = mock_anon.check_availability.await_args.kwargs
        assert call_kwargs["business_id"] == "biz-T3-001"
        assert call_kwargs["biz_item_id"] == "item-T3-001"
        assert call_kwargs["target_date"] == "2026-04-25"
        assert call_kwargs["use_cache"] is False
        assert call_kwargs["schedule_id"] == 9900

        # execute_with_tab 미호출
        worker.browser.execute_with_tab.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_legacy_schedule_routes_to_execute_with_tab(self):
        """
        T3: legacy 모드 → browser.execute_with_tab 호출, get_anonymous_monitor 미호출.
        """
        from app.worker.naver_monitor_worker import NaverMonitorWorker
        from app.worker.naver_monitor_cycle import NaverMonitorCycleRunner
        from app.modules.naver_booking.services.site_monitor import FetchResult

        worker = NaverMonitorWorker()
        worker._site_monitor = MagicMock()
        worker.browser = MagicMock()
        worker.browser.execute_with_tab = AsyncMock(
            return_value=FetchResult(hash=42, slots=[], status="no_slots")
        )
        worker._cycle_runner = NaverMonitorCycleRunner(
            site_monitor=worker._site_monitor, browser_manager=worker.browser
        )

        schedule_meta = _make_schedule_meta(monitoring_mode="legacy")

        with patch(
            "app.modules.naver_booking.services.anonymous_monitor.get_anonymous_monitor"
        ) as mock_get_anon:
            with patch("app.services.event_logger.EventLogger.log_monitoring_event"):
                await worker._execute_monitoring_cycle(schedule_meta)

        worker.browser.execute_with_tab.assert_awaited_once()
        mock_get_anon.assert_not_called()

    @pytest.mark.asyncio
    async def test_anonymous_schedule_persists_event_with_anonymous_api(self):
        """
        T3: anonymous 모드 → EventLogger.log_monitoring_event에 fetch_method='anonymous_api' 전달.

        T1과의 차이: _run_anonymous_cycle 전체 코드 경로 실행 후 EventLogger 계약 확인.
        """
        from app.worker.naver_monitor_worker import NaverMonitorWorker
        from app.worker.naver_monitor_cycle import NaverMonitorCycleRunner

        worker = NaverMonitorWorker()
        worker._site_monitor = MagicMock()
        worker._cycle_runner = NaverMonitorCycleRunner(
            site_monitor=worker._site_monitor, browser_manager=MagicMock()
        )

        mock_anon = MagicMock()
        mock_anon.check_availability = AsyncMock(
            return_value=_make_anon_availability(slots=[
                _make_slot("2026-04-25 10:00:00", unit_stock=3, unit_booking_count=1)
            ])
        )

        schedule_meta = _make_schedule_meta(monitoring_mode="anonymous")

        with patch(
            "app.modules.naver_booking.services.anonymous_monitor.get_anonymous_monitor",
            return_value=mock_anon,
        ):
            with patch("app.services.event_logger.EventLogger.log_monitoring_event") as mock_log:
                await worker._execute_monitoring_cycle(schedule_meta)

        assert mock_log.call_count == 1
        logged_kwargs = mock_log.call_args.kwargs
        assert logged_kwargs["fetch_method"] == "anonymous_api", (
            f"anonymous 모드인데 fetch_method={logged_kwargs['fetch_method']}"
        )
        assert logged_kwargs["schedule_id"] == 9900

    @pytest.mark.asyncio
    async def test_anonymous_available_result_logs_event_and_sends_notification(self):
        """
        T3: anonymous available result가 EventLogger 기록 뒤 worker notification mock까지 이어진다.
        """
        from app.worker.naver_monitor_worker import NaverMonitorWorker
        from app.worker.naver_monitor_cycle import NaverMonitorCycleRunner

        worker = NaverMonitorWorker()
        worker._site_monitor = MagicMock()
        worker._cycle_runner = NaverMonitorCycleRunner(
            site_monitor=worker._site_monitor, browser_manager=MagicMock()
        )
        worker._notification_service = MagicMock()
        worker._notification_service.send_notification_message = AsyncMock()

        schedule_meta = _make_schedule_meta(monitoring_mode="anonymous")
        schedule_meta["is_enabled"] = True
        worker._active_schedules[schedule_meta["id"]] = dict(schedule_meta, last_slots=[])

        mock_anon = MagicMock()
        mock_anon.check_availability = AsyncMock(
            return_value=_make_anon_availability(slots=[
                _make_slot("2026-04-25 10:00:00", unit_stock=3, unit_booking_count=1)
            ])
        )

        with patch(
            "app.modules.naver_booking.services.anonymous_monitor.get_anonymous_monitor",
            return_value=mock_anon,
        ):
            with patch("app.services.event_logger.EventLogger.log_monitoring_event") as mock_log:
                with patch.object(worker, "_update_schedule_run_state", AsyncMock()):
                    await worker._check_schedule(dict(schedule_meta))

        assert mock_log.call_count == 1
        assert mock_log.call_args.kwargs["status"] == "available"
        worker._notification_service.send_notification_message.assert_awaited_once()
        message = worker._notification_service.send_notification_message.await_args.args[0]
        assert "10:00" in message
        assert schedule_meta["url"] in message


class TestAdapterSlotFormatIntegration:
    """
    _adapt_anonymous_result 슬롯 포맷이 site_monitor.py legacy 포맷과 동일한지 검증.

    legacy 포맷: f"{slot_time} ({available_count}매)"
    어댑터 포맷: f"{s.start_time} ({max(s.unit_stock - s.unit_booking_count, 0)}매)"
    """

    def test_adapter_slot_format_matches_site_monitor_output(self):
        """T3: 어댑터 출력 슬롯 포맷이 legacy 정규식 패턴과 일치."""
        from app.worker.naver_monitor_cycle import NaverMonitorCycleRunner

        runner = NaverMonitorCycleRunner(site_monitor=MagicMock(), browser_manager=MagicMock())
        slots = [
            _make_slot("2026-04-25 10:00:00", unit_stock=5, unit_booking_count=2),
            _make_slot("2026-04-25 11:30:00", unit_stock=3, unit_booking_count=0),
        ]
        availability = _make_anon_availability(slots=slots)

        result = runner._adapt_anonymous_result(availability, current_hash=0, current_slots=[])

        pattern = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \(\d+매\)$")
        assert len(result.slots) == 2
        for slot_str in result.slots:
            assert pattern.match(slot_str), f"legacy 포맷 불일치: {slot_str}"

        # 구체적 값 검증
        assert result.slots[0] == "2026-04-25 10:00:00 (3매)"   # 5-2=3
        assert result.slots[1] == "2026-04-25 11:30:00 (3매)"   # 3-0=3

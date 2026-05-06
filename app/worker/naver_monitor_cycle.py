"""monitoring_mode별 사이클 실행 모듈.

NaverMonitorCycleRunner는 단일 네이버 스케줄을 monitoring_mode(legacy/anonymous)에 따라
체크하는 책임만 가진다. DB 상태 갱신·스케줄 수명주기 관리는 NaverMonitorWorker가 담당한다.
"""
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, TYPE_CHECKING

from app.services.event_logger import EventLogger
from app.services.schedule_service import calculate_default_interval
from app.modules.naver_booking.services.booking_utils import filter_slots_by_time_range
from app.modules.naver_booking.services.site_monitor import (
    FetchResult,
    NaverSiteMonitor,
    filter_slots_by_times,
)
from app.schemas.monitor_schedule import coerce_monitoring_mode

if TYPE_CHECKING:
    from app.shared.browser.browser_manager import BrowserManager
    from app.modules.naver_booking.services.anonymous_monitor import AvailabilityResult

logger = logging.getLogger(__name__)


class NaverMonitorCycleRunner:
    """monitoring_mode별 단일 사이클 실행기.

    Args:
        site_monitor: 레거시(탭) 모드에서 사용하는 NaverSiteMonitor 인스턴스.
        browser_manager: 레거시 모드 탭 획득에 사용하는 BrowserManager 인스턴스.
    """

    def __init__(
        self,
        site_monitor: "NaverSiteMonitor",
        browser_manager: "BrowserManager",
    ) -> None:
        self._site_monitor = site_monitor
        self._browser = browser_manager

    # ---- static helpers ----

    @staticmethod
    def _build_schedule_tag(schedule_meta: Dict[str, Any]) -> str:
        """로그/알림용 스케줄 태그."""
        return (
            f"{schedule_meta.get('business_name', 'Naver')}/"
            f"{schedule_meta.get('naver_biz_item_id', schedule_meta['biz_item_id'])}/"
            f"schedule:{schedule_meta['id']}"
        )

    @staticmethod
    def _deserialize_schedule_times(raw_times: Any) -> List[str]:
        """times 필드를 문자열/JSON/list 형태 모두 지원해 정규화한다."""
        if raw_times is None:
            return []
        if isinstance(raw_times, list):
            return [str(item) for item in raw_times]
        if isinstance(raw_times, str):
            try:
                parsed = json.loads(raw_times)
            except json.JSONDecodeError:
                return [raw_times]
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
            return [str(parsed)]
        return [str(raw_times)]

    @staticmethod
    def _calculate_next_run_time(
        schedule_meta: Dict[str, Any], checked_at: datetime
    ) -> datetime:
        """다음 실행 예정 시각을 계산한다."""
        interval = schedule_meta.get("interval")
        if interval is None:
            interval = calculate_default_interval(schedule_meta.get("date"))
        try:
            seconds = max(float(interval), 1.0)
        except (TypeError, ValueError):
            seconds = 60.0
        return checked_at + timedelta(seconds=seconds)

    # ---- anonymous mode ----

    async def _run_anonymous_cycle(
        self,
        schedule_meta: Dict[str, Any],
        current_hash: int,
        current_slots: List[str],
    ) -> FetchResult:
        """탭 미사용(HTTP 직접) 익명 모니터링 사이클."""
        from app.modules.naver_booking.services.anonymous_monitor import get_anonymous_monitor
        anon = get_anonymous_monitor()
        availability = await anon.check_availability(
            business_type_id=int(schedule_meta["business_type_id"]),
            business_id=schedule_meta["naver_business_id"],
            biz_item_id=schedule_meta["naver_biz_item_id"],
            target_date=schedule_meta["date"],
            use_cache=False,
            schedule_id=schedule_meta["id"],
        )
        return self._adapt_anonymous_result(availability, current_hash, current_slots)

    def _adapt_anonymous_result(
        self,
        availability: "AvailabilityResult",
        current_hash: int,
        current_slots: List[str],
    ) -> FetchResult:
        """AvailabilityResult → FetchResult 어댑터.

        slot 문자열 포맷: "{start_time} ({remaining}매)" — site_monitor.py:1000 legacy 포맷과 동일.
        """
        if availability.error:
            return FetchResult(
                hash=current_hash,
                slots=list(current_slots),
                status="error",
                reason=availability.error,
            )
        if availability.slots:
            slot_strs = [
                f"{s.start_time} ({max(s.unit_stock - s.unit_booking_count, 0)}매)"
                for s in availability.slots
            ]
            return FetchResult(hash=hash(str(slot_strs)), slots=slot_strs, status="available")
        return FetchResult(hash=hash(str([])), slots=[], status="no_slots")

    # ---- main entry ----

    async def execute_monitoring_cycle(
        self, schedule_meta: Dict[str, Any]
    ) -> Dict[str, Any]:
        """단일 네이버 스케줄을 monitoring_mode(legacy/anonymous)에 따라 체크한다.

        Returns:
            dict with keys: checked_at, next_run_time, event_status,
                            last_slots, last_data_hash, error_message
        """
        monitoring_mode = coerce_monitoring_mode(schedule_meta.get("monitoring_mode"))
        source_type = schedule_meta.get("source_type") or "manual"
        logger.info(
            f"[naver_monitor] mode={monitoring_mode} source_type={source_type} "
            f"schedule_id={schedule_meta['id']}"
        )

        if not self._site_monitor:
            raise RuntimeError("NaverSiteMonitor가 초기화되지 않았습니다.")

        current_slots = list(schedule_meta.get("last_slots") or [])
        current_hash = schedule_meta.get("last_data_hash")
        if current_hash is None:
            current_hash = hash(str(current_slots))

        tag = self._build_schedule_tag(schedule_meta)
        started_at = time.perf_counter()

        if monitoring_mode == "anonymous":
            fetch_result = await self._run_anonymous_cycle(
                schedule_meta, current_hash, current_slots
            )
        else:
            if not self._browser:
                raise RuntimeError("BrowserManager가 초기화되지 않았습니다.")

            async def monitor_callback(page):
                return await self._site_monitor.perform_task_with_fetch(
                    page,
                    schedule_meta["url"],
                    tag,
                    current_hash,
                    current_slots,
                )

            fetch_result = await self._browser.execute_with_tab(
                callback=monitor_callback,
                service_account_id=schedule_meta.get("service_account_id"),
                target_id=schedule_meta["id"],
                tab_timeout=max(60.0, float(schedule_meta.get("interval") or 60.0)),
                operation_timeout=max(
                    60.0,
                    float(schedule_meta.get("interval") or 60.0) + 30.0,
                ),
            )

        checked_at = datetime.now()
        response_time_ms = (time.perf_counter() - started_at) * 1000

        original_slots = list(fetch_result.slots or [])
        filtered_slots = list(original_slots)
        time_range = schedule_meta.get("time_range")
        if time_range:
            filtered_slots = filter_slots_by_time_range(filtered_slots, time_range)

        target_times = self._deserialize_schedule_times(schedule_meta.get("times"))
        if target_times:
            filtered_slots = filter_slots_by_times(filtered_slots, target_times)

        event_status = fetch_result.status
        slots_for_event = list(filtered_slots) if event_status == "available" else list(original_slots)
        if event_status == "available" and not filtered_slots:
            event_status = "no_slots"
            slots_for_event = []

        target_time_matched = bool(filtered_slots) if (time_range or target_times) else bool(original_slots)
        error_message = fetch_result.reason if event_status == "error" else None

        fetch_method = "anonymous_api" if monitoring_mode == "anonymous" else "graphql_api"
        EventLogger.log_monitoring_event(
            schedule_id=schedule_meta["id"],
            event_type="check",
            status=event_status,
            available_count=len(slots_for_event) if event_status == "available" else 0,
            slots_info=slots_for_event,
            error_message=error_message,
            timestamp=checked_at,
            response_time_ms=response_time_ms,
            data_hash=str(fetch_result.hash),
            hash_changed=fetch_result.hash != current_hash,
            fetch_method=fetch_method,
            time_range=time_range,
            original_slot_count=len(original_slots),
            filtered_slot_count=len(filtered_slots),
            target_time_matched=target_time_matched,
            booking_triggered=False,
            booking_success=None,
        )

        return {
            "checked_at": checked_at,
            "next_run_time": self._calculate_next_run_time(schedule_meta, checked_at),
            "event_status": event_status,
            "last_slots": list(slots_for_event),
            "last_data_hash": fetch_result.hash,
            "error_message": error_message,
        }

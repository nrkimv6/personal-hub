"""
쿠팡 여행상품 모니터링 서비스.

상태 추적, 변경 감지, 알림 발송, DB 이벤트 로깅을 담당합니다.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Dict, List, Optional, TYPE_CHECKING

from app.core.config import settings
from app.modules.availability.types import AvailabilityCheckResult
from app.modules.availability.services.event_writer import write_availability_event
from app.modules.coupang_travel.services.availability_adapter import (
    is_vendor_item_available,
    vendor_items_to_availability_result,
)
from app.modules.coupang_travel.services.api_client import CoupangApiClient, VendorItem
from app.services.event_logger import EventLogger

if TYPE_CHECKING:
    from playwright.async_api import Page
    from app.shared.notification import NotificationService

logger = logging.getLogger(__name__)

@dataclass
class VendorItemStatus:
    sale_status: str
    stock_count: int
    last_update: datetime = field(default_factory=datetime.now)


@dataclass
class StatusChange:
    date: str
    item_name: str
    old_status: str
    new_status: str
    old_stock: int
    new_stock: int


def _make_vendor_key(vi: VendorItem, index: int) -> str:
    """안정적인 상태 키 생성. 이름 기반 fallback."""
    if vi.vendor_item_name:
        return vi.vendor_item_name
    return f"item_{index}"


class CoupangMonitorService:
    """쿠팡 여행상품 상태 추적 + 변경 감지 + 알림 서비스."""

    def __init__(
        self,
        api_client: CoupangApiClient,
        notification_service: "NotificationService",
        db_logging: bool = True,
    ):
        self._api_client = api_client
        self._notification_service = notification_service
        self._db_logging = db_logging
        # 키: "{product_id}_{date}_{vendor_key}" -> VendorItemStatus
        self._previous_statuses: Dict[str, VendorItemStatus] = {}

    async def check_and_notify(
        self,
        product_id: str,
        vendor_item_package_id: str,
        dates: List[str],
        page: Optional["Page"] = None,
        schedule_id: Optional[int] = None,
        notify_times: Optional[List[str]] = None,
        prefetched_items: Optional[List[VendorItem]] = None,
        prefetched_response_time_ms: float = 0.0,
        prefetched_checked_at: Optional[datetime] = None,
    ) -> List[StatusChange]:
        """각 date별 상태를 체크하고 변경 시 알림 발송.

        최초 호출(키 없음)은 상태 저장만 하고 알림은 보내지 않는다.

        Args:
            prefetched_items: HTTP 클라이언트로 미리 가져온 아이템 목록.
                              제공 시 page 경로 skip. dates는 단일 date여야 함.
            prefetched_response_time_ms: prefetched_items 획득에 걸린 시간.
            prefetched_checked_at: HTTP 응답 수신 시각.
            event_timestamp: 응답 기반 성공/무재고 이벤트만 전달되는
                            시각(에러/no-response는 None).

        Returns:
            변경된 StatusChange 목록
        """
        changes: List[StatusChange] = []

        for date in dates:
            if prefetched_items is not None:
                # HTTP 클라이언트로 미리 가져온 아이템 사용
                items = prefetched_items
                response_time_ms = prefetched_response_time_ms
                event_timestamp = prefetched_checked_at
            else:
                if page is None:
                    logger.error(
                        "[CoupangMonitorService] page와 prefetched_items 모두 없음 (product_id=%s, date=%s)",
                        product_id, date,
                    )
                    continue
                started_at = time.perf_counter()
                items = await self._api_client.fetch_vendor_items(
                    product_id=product_id,
                    vendor_item_package_id=vendor_item_package_id,
                    select_date=date,
                    page=page,
                )
                response_time_ms = (time.perf_counter() - started_at) * 1000
                event_timestamp = datetime.now()

            if items is None:
                logger.warning(
                    "[CoupangMonitorService] API 응답 없음 (product_id=%s, date=%s)",
                    product_id,
                    date,
                )
                self._log_monitoring_event(
                    schedule_id=schedule_id,
                    status="error",
                    available_count=0,
                    slots_info=None,
                    error_message="Coupang vendor-items API returned no response",
                    response_time_ms=response_time_ms,
                )
                continue

            for idx, vi in enumerate(items):
                vendor_key = _make_vendor_key(vi, idx)
                state_key = f"{product_id}_{date}_{vendor_key}"
                current = VendorItemStatus(
                    sale_status=vi.sale_status,
                    stock_count=vi.stock_count,
                )

                if state_key not in self._previous_statuses:
                    # 최초: 상태만 저장, 알림 없음
                    self._previous_statuses[state_key] = current
                    continue

                prev = self._previous_statuses[state_key]
                status_changed = prev.sale_status != current.sale_status
                stock_changed = prev.stock_count != current.stock_count

                if status_changed or stock_changed:
                    change = StatusChange(
                        date=date,
                        item_name=vi.vendor_item_name,
                        old_status=prev.sale_status,
                        new_status=current.sale_status,
                        old_stock=prev.stock_count,
                        new_stock=current.stock_count,
                    )
                    changes.append(change)
                    self._previous_statuses[state_key] = current
                    core_notify = self._is_within_notify_times(notify_times)
                    kakao_notify = self._should_send_kakao_alert(date, change)

                    if not core_notify and not kakao_notify:
                        logger.warning(
                            "[CoupangMonitorService] 알림 제외: date=%s item=%s core_notify=%s kakao_notify=%s",
                            change.date,
                            change.item_name,
                            core_notify,
                            kakao_notify,
                        )
                        continue

                    logger.warning(
                        "[CoupangMonitorService] 알림 전송 결정: date=%s item=%s core_notify=%s kakao_notify=%s",
                        change.date,
                        change.item_name,
                        core_notify,
                        kakao_notify,
                    )
                    await self._send_notification(
                        change,
                        send_telegram=core_notify,
                        send_desktop=core_notify,
                        send_kakao=kakao_notify,
                        kakao_metadata={
                            "date": change.date,
                            "item_name": change.item_name,
                            "old_status": change.old_status,
                            "new_status": change.new_status,
                            "old_stock": change.old_stock,
                            "new_stock": change.new_stock,
                        },
                    )

            result = vendor_items_to_availability_result(
                items,
                response_time_ms=response_time_ms,
            )
            self._log_availability_event(
                schedule_id=schedule_id,
                result=result,
                event_timestamp=event_timestamp,
            )

        return changes

    @staticmethod
    def _is_within_notify_times(times: Optional[List[str]]) -> bool:
        """현재 시각이 알림 허용 시간대 내에 있는지 판정.

        times=None이면 항상 True (미설정 = 모든 시간에 알림).
        개별 시간 "HH:MM" 정확 일치 + 범위 "HH:MM-HH:MM" 구간 포함(start <= now <= end) 지원.
        인식할 수 없는 형식 항목은 True 반환 (안전 기본값 — 알림 억제보다 허용 우선).
        """
        import re
        _time_re = re.compile(r'^\d{2}:\d{2}$')

        if times is None:
            return True
        now_str = datetime.now().strftime("%H:%M")
        for entry in times:
            try:
                if "-" in entry:
                    parts = entry.split("-", 1)
                    start, end = parts[0], parts[1]
                    if not (_time_re.match(start) and _time_re.match(end)):
                        return True  # 파싱 불가 → 안전 기본값
                    if start <= now_str <= end:
                        return True
                else:
                    if not _time_re.match(entry):
                        return True  # 파싱 불가 → 안전 기본값
                    if entry == now_str:
                        return True
            except Exception:
                return True  # 예외 안전 기본값
        return False

    @staticmethod
    def _is_item_available(item: VendorItem) -> bool:
        return is_vendor_item_available(item)

    @staticmethod
    def _build_slots_info(items: List[VendorItem]) -> List[dict]:
        """MonitoringEvent.slots_info에 저장할 구조를 생성."""
        return [
            {
                "vendorItemName": item.vendor_item_name,
                "saleStatus": item.sale_status,
                "stockCount": item.stock_count,
            }
            for item in items
        ]

    @staticmethod
    def _normalize_alert_item_name(item_name: Optional[str]) -> str:
        """알림 메시지용 옵션 라벨 정규화."""
        raw = (item_name or "").strip()
        if not raw:
            return "옵션 미확인"
        normalized = raw.replace("메가뷰티쇼 버추얼스토어", "", 1).strip()
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized or "옵션 미확인"

    @staticmethod
    def _should_send_kakao_alert(date: str, change: StatusChange) -> bool:
        """메가뷰티쇼 카카오 알림 대상인지 판정."""
        if not bool(getattr(settings, "MEGABEAUTY_KAKAO_ALERT_ENABLED", False)):
            logger.warning(
                "[CoupangMonitorService] Kakao 알림 비활성화로 제외: date=%s item=%s",
                date,
                change.item_name,
            )
            return False
        configured_dates = str(
            getattr(settings, "MEGABEAUTY_KAKAO_ALERT_DATES", "*") or ""
        ).strip()
        wildcard_tokens = {"*", "any", "all", "true", "on"}
        if configured_dates:
            normalized = configured_dates.strip().strip("[]")
            raw_tokens = re.split(r"[,\n;]", normalized)
            tokens = []
            for token in raw_tokens:
                cleaned = token.strip().strip("'\"")
                if cleaned:
                    tokens.append(cleaned)
            lowered_tokens = {token.casefold() for token in tokens}
            if lowered_tokens and not (lowered_tokens & wildcard_tokens):
                allowed_dates = set(tokens)
                if date not in allowed_dates:
                    logger.info(
                        "[CoupangMonitorService] Kakao 알림 날짜 필터로 제외: date=%s allowed=%s",
                        date,
                        sorted(allowed_dates),
                    )
                    return False
            elif not lowered_tokens:
                logger.warning(
                    "[CoupangMonitorService] Kakao 날짜 설정 파싱 실패/공백으로 감지됨. "
                    "알림 누락 방지를 위해 날짜 필터를 비활성화합니다. raw=%r",
                    configured_dates,
                )

        keyword = (getattr(settings, "MEGABEAUTY_KAKAO_ALERT_ITEM_NAME_KEYWORD", "") or "").strip()
        if keyword:
            candidate = " ".join(
                part for part in [
                    change.item_name,
                    change.old_status,
                    change.new_status,
                ]
                if part
            )
            if keyword.casefold() not in candidate.casefold():
                logger.debug(
                    "[CoupangMonitorService] Kakao 키워드 미일치지만 날짜 조건으로 알림 허용: date=%s keyword=%s item=%s",
                    date,
                    keyword,
                    change.item_name,
                )
        return True

    def _map_monitor_status(
        self,
        items: List[VendorItem],
        changes: List[StatusChange],
        api_error: bool = False,
    ) -> str:
        """쿠팡 체크 결과를 공통 이벤트 상태로 정규화."""
        if api_error:
            return "error"
        if any(self._is_item_available(item) for item in items):
            return "available"
        return "no_slots"

    def _log_monitoring_event(
        self,
        schedule_id: Optional[int],
        status: str,
        available_count: int,
        slots_info: Optional[List[dict]],
        response_time_ms: Optional[float] = None,
        event_timestamp: Optional[datetime] = None,
        error_message: Optional[str] = None,
    ) -> None:
        if not self._db_logging:
            return
        if schedule_id is None:
            logger.warning(
                "[CoupangMonitorService] schedule_id 없음으로 DB 이벤트 로깅 생략"
            )
            return

        event_type = "check"
        if status == "available":
            event_type = "slot_detected"
        elif status == "error":
            event_type = "error"

        try:
            EventLogger.log_monitoring_event(
                schedule_id=schedule_id,
                event_type=event_type,
                status=status,
                available_count=available_count,
                # error/no-response는 응답 수신 시각을 덮어쓰지 않도록 None으로 둔다.
                timestamp=event_timestamp,
                slots_info=slots_info,
                error_message=error_message,
                response_time_ms=response_time_ms,
            )
        except Exception as e:
            logger.error(
                "[CoupangMonitorService] DB 이벤트 로깅 실패 (schedule_id=%s): %s",
                schedule_id,
                e,
            )

    def _log_availability_event(
        self,
        schedule_id: Optional[int],
        result: AvailabilityCheckResult,
        event_timestamp: Optional[datetime] = None,
    ) -> None:
        if not self._db_logging:
            return
        if schedule_id is None:
            logger.warning(
                "[CoupangMonitorService] schedule_id 없음으로 DB 이벤트 로깅 생략"
            )
            return

        try:
            write_availability_event(
                schedule_id=schedule_id,
                result=result,
                timestamp=event_timestamp,
                event_logger=EventLogger,
            )
        except Exception as e:
            logger.error(
                "[CoupangMonitorService] DB 이벤트 로깅 실패 (schedule_id=%s): %s",
                schedule_id,
                e,
            )

    async def _send_notification(
        self,
        change: StatusChange,
        *,
        send_telegram: bool = True,
        send_desktop: bool = True,
        send_kakao: bool = False,
        kakao_metadata: Optional[dict] = None,
    ) -> None:
        """변경 알림 발송."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item_name = self._normalize_alert_item_name(change.item_name)
        # 일부 채널에서 개행이 소실되어도 가독성을 유지하도록 단일 라인 포맷을 사용한다.
        message = (
            "[쿠팡][재고알림] "
            f"옵션={item_name} | "
            f"재고={change.new_stock}개 | "
            f"감지시각={now_str}"
        )
        try:
            await self._notification_service.send_notification_message(
                message,
                send_telegram=send_telegram,
                send_desktop=send_desktop,
                send_kakao=send_kakao,
                kakao_metadata=kakao_metadata,
            )
        except Exception as e:
            logger.error("[CoupangMonitorService] 알림 발송 실패: %s", e)

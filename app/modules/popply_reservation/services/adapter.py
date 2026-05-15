"""POPPLY reservation API response adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.modules.availability.types import AvailabilityCheckResult, AvailabilitySlot
from app.modules.popply_reservation.services.http_client import PopplyHttpClient
from app.modules.popply_reservation.utils.hash_normalizer import normalize_schedule_group_hash


def _reservation_schedules(payload: Any) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    candidates = [
        payload.get("reservationSchedule"),
        payload.get("reservationSchedules"),
        payload.get("data", {}).get("reservationSchedule") if isinstance(payload.get("data"), dict) else None,
        payload.get("data", {}).get("reservationSchedules") if isinstance(payload.get("data"), dict) else None,
        (
            payload.get("data", {}).get("reservation", {}).get("reservationSchedule")
            if isinstance(payload.get("data"), dict)
            and isinstance(payload.get("data", {}).get("reservation"), dict)
            else None
        ),
        (
            payload.get("data", {}).get("reservation", {}).get("reservationSchedules")
            if isinstance(payload.get("data"), dict)
            and isinstance(payload.get("data", {}).get("reservation"), dict)
            else None
        ),
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def _parse_start_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


class PopplyReservationAdapter:
    def __init__(self, client: Optional[PopplyHttpClient] = None):
        self.client = client or PopplyHttpClient()

    async def check(
        self,
        *,
        store_id: str,
        reservation_type: str,
        target_schedule_group: str,
        schedule_date: str,
        now: Optional[datetime] = None,
    ) -> AvailabilityCheckResult:
        started = datetime.now()
        try:
            payload = await self.client.fetch_reservation(store_id, reservation_type)
        except Exception as exc:
            return AvailabilityCheckResult(
                source_type="popply",
                raw=None,
                fetch_method="anonymous_api",
                response_time_ms=(datetime.now() - started).total_seconds() * 1000,
                error_message=str(exc),
            )

        schedules = _reservation_schedules(payload)
        if not schedules:
            return AvailabilityCheckResult(
                source_type="popply",
                raw=payload,
                fetch_method="anonymous_api",
                response_time_ms=(datetime.now() - started).total_seconds() * 1000,
                error_message="reservationSchedule missing",
            )

        current = now or datetime.now()
        normalized_target_schedule_group = normalize_schedule_group_hash(target_schedule_group)
        slots: list[AvailabilitySlot] = []
        for item in schedules:
            schedule_group = item.get("scheduleGroup")
            if normalize_schedule_group_hash(schedule_group) != normalized_target_schedule_group:
                continue
            start_time = _parse_start_time(item.get("reservationStartTime"))
            reservation_date = item.get("reservationDate") or (
                start_time.strftime("%Y-%m-%d") if start_time else None
            )
            if reservation_date and reservation_date != schedule_date:
                continue
            if start_time and start_time <= current:
                continue
            available_count = int(item.get("currentAvailableGuests") or 0)
            slots.append(
                AvailabilitySlot(
                    source_type="popply",
                    available_count=max(0, available_count),
                    label=item.get("reservationStartTime") or item.get("scheduleName"),
                    slot_id=str(item.get("id") or item.get("reservationScheduleId") or schedule_group),
                    raw={
                        **item,
                        "sourceType": "popply",
                        "storeId": store_id,
                        "reservationType": reservation_type,
                    },
                )
            )

        return AvailabilityCheckResult(
            source_type="popply",
            slots=slots,
            raw=payload,
            fetch_method="anonymous_api",
            response_time_ms=(datetime.now() - started).total_seconds() * 1000,
        )

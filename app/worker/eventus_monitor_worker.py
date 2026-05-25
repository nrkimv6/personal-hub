"""Eventus reservation availability monitor worker."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from app.database import SessionLocal
from app.models.monitor_schedule import MonitorSchedule
from app.models.monitoring_event import MonitoringEvent
from app.modules.availability.services.change_detector import detect_availability_change
from app.modules.availability.services.event_writer import write_availability_event
from app.modules.availability.services.state import determine_availability_status
from app.modules.eventus_reservation.services.adapter import EventusReservationAdapter
from app.modules.eventus_reservation.services.notification import build_eventus_slot_message
from app.services.schedule_service import ScheduleService
from app.shared.notification import NotificationService
from app.shared.worker.base_worker import BaseWorker

logger = logging.getLogger(__name__)
schedule_service = ScheduleService()


class EventusMonitorWorker(BaseWorker):
    LOOP_INTERVAL = 60.0  # Eventus pages are SSR; poll every 60s

    def __init__(
        self,
        browser_manager=None,
        adapter: Optional[EventusReservationAdapter] = None,
        notification_service: Optional[NotificationService] = None,
    ):
        super().__init__("eventus_monitor", browser_manager)
        self.adapter = adapter or EventusReservationAdapter()
        self.notification_service = notification_service or NotificationService()

    def _get_loop_interval(self) -> float:
        return self.LOOP_INTERVAL

    async def _main_loop_iteration(self) -> None:
        db = SessionLocal()
        try:
            schedules = schedule_service.get_all_with_context(
                db, is_enabled=True, service_type="eventus"
            )
        finally:
            db.close()

        for ctx in schedules:
            await self._safe_execute(
                f"check_eventus_schedule_{ctx['id']}",
                lambda c=ctx: self._check_schedule(c),
            )

    async def _check_schedule(self, ctx: dict) -> None:
        schedule_id = ctx.get("id")
        db = SessionLocal()
        try:
            schedule = db.query(MonitorSchedule).filter(MonitorSchedule.id == schedule_id).first()
            if schedule is None:
                return

            item = schedule.biz_item
            extra: dict = {}
            if item.extra_desc_json:
                try:
                    parsed = json.loads(item.extra_desc_json)
                    extra = parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    logger.warning(
                        "[eventus_monitor] extra_desc_json parse failed schedule_id=%s",
                        schedule_id,
                    )

            source_url = extra.get("source_url") or item.base_url
            if not source_url:
                logger.error(
                    "[eventus_monitor] source_url missing schedule_id=%s",
                    schedule_id,
                )
                return

            previous_event = (
                db.query(MonitoringEvent)
                .filter(MonitoringEvent.schedule_id == schedule.id)
                .order_by(MonitoringEvent.timestamp.desc(), MonitoringEvent.id.desc())
                .first()
            )
            previous_status = previous_event.status if previous_event else None

            schedule.is_active = True
            schedule.run_status = "running"
            db.commit()

            result = await self.adapter.check(
                source_url=source_url,
                schedule_date=schedule.date,
                target_bundle_id=extra.get("selected_bundle_id"),
                target_time_key=extra.get("selected_time_key"),
            )
            write_availability_event(schedule.id, result)
            current_status = determine_availability_status(
                result.slots,
                available_count=result.available_count,
                error_message=result.error_message,
            )
            change = detect_availability_change(previous_status, current_status)
            if change.should_notify:
                available_slots = [slot for slot in result.slots if slot.is_available]
                message = build_eventus_slot_message(item.name, schedule.date, available_slots)
                await self.notification_service.send_notification_message(message)

            schedule.last_check_time = datetime.now()
            schedule.run_status = "idle"
            schedule.is_active = False
            db.commit()

        except Exception:
            db.rollback()
            logger.exception(
                "[eventus_monitor] schedule check failed schedule_id=%s",
                schedule_id,
            )
            raise
        finally:
            db.close()

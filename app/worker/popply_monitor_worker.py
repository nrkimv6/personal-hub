"""POPPLY reservation availability monitor worker."""

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
from app.modules.popply_reservation.services.adapter import PopplyReservationAdapter
from app.modules.popply_reservation.services.notification import build_popply_slot_message
from app.services.schedule_service import ScheduleService
from app.shared.notification import NotificationService
from app.shared.worker.base_worker import BaseWorker

logger = logging.getLogger(__name__)
schedule_service = ScheduleService()


class PopplyMonitorWorker(BaseWorker):
    LOOP_INTERVAL = 30.0

    def __init__(
        self,
        browser_manager=None,
        adapter: Optional[PopplyReservationAdapter] = None,
        notification_service: Optional[NotificationService] = None,
    ):
        super().__init__("popply_monitor", browser_manager)
        self.adapter = adapter or PopplyReservationAdapter()
        self.notification_service = notification_service or NotificationService()

    def _get_loop_interval(self) -> float:
        return self.LOOP_INTERVAL

    async def _main_loop_iteration(self) -> None:
        db = SessionLocal()
        try:
            schedules = schedule_service.get_all_with_context(
                db, is_enabled=True, service_type="popply"
            )
        finally:
            db.close()

        for ctx in schedules:
            await self._safe_execute(
                f"check_popply_schedule_{ctx['id']}",
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
            extra = json.loads(item.extra_desc_json or "{}")
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
                store_id=str(extra.get("store_id") or item.biz_item_id),
                reservation_type=str(extra.get("reservation_type") or "PRE"),
                target_schedule_group=str(extra.get("schedule_group") or ""),
                schedule_date=schedule.date,
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
                message = build_popply_slot_message(item.name, schedule.date, available_slots)
                await self.notification_service.send_notification_message(message)
            schedule.last_check_time = datetime.now()
            schedule.run_status = "idle"
            schedule.is_active = False
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("[popply_monitor] schedule check failed schedule_id=%s", schedule_id)
            raise
        finally:
            db.close()

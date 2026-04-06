"""Popup URL monitor worker."""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from app.database import SessionLocal
from app.models.popup_url_monitor import PopupUrlMonitor
from app.modules.naver_popup_monitor.services.monitor_service import PopupMonitorService
from app.shared.worker.base_worker import BaseWorker

if TYPE_CHECKING:
    from app.shared.browser.browser_manager import BrowserManager

logger = logging.getLogger(__name__)


class PopupMonitorWorker(BaseWorker):
    """Run popup URL monitors in fixed interval."""

    LOOP_INTERVAL = 60.0

    def __init__(self, browser_manager: Optional["BrowserManager"] = None):
        super().__init__("popup_monitor", browser_manager)
        self._monitor_service = PopupMonitorService()

    def _get_loop_interval(self) -> float:
        return self.LOOP_INTERVAL

    async def _main_loop_iteration(self) -> None:
        db = SessionLocal()
        try:
            monitor_ids = [
                row[0]
                for row in db.query(PopupUrlMonitor.id)
                .filter(PopupUrlMonitor.is_enabled.is_(True))
                .order_by(PopupUrlMonitor.id.asc())
                .all()
            ]
        finally:
            db.close()

        for monitor_id in monitor_ids:
            await self._safe_execute(
                f"popup_monitor_{monitor_id}",
                lambda mid=monitor_id: self._run_single(mid),
            )

    async def _run_single(self, monitor_id: int) -> None:
        db = SessionLocal()
        try:
            await self._monitor_service.run_monitor_by_id(
                db,
                monitor_id,
                trigger="worker",
            )
        finally:
            db.close()

    async def _cleanup(self):
        await self._monitor_service.close()
        await super()._cleanup()


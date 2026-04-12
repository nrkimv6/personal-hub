"""
쿠팡 여행상품 취소표 모니터링 워커.

쿠팡 vendor-items API를 폴링하여 saleStatus/stockCount 변경 시 알림 발송.
네이버 워커와 독립적으로 동작하며 browser_manager를 공유합니다.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional, TYPE_CHECKING

from app.shared.worker.base_worker import BaseWorker
from app.database import SessionLocal
from app.services.schedule_service import ScheduleService

if TYPE_CHECKING:
    from app.shared.browser.browser_manager import BrowserManager

logger = logging.getLogger(__name__)

schedule_service = ScheduleService()


class CoupangMonitorWorker(BaseWorker):
    """쿠팡 여행상품 취소표 모니터링 워커."""

    LOOP_INTERVAL = 30.0  # 30초

    def __init__(self, browser_manager: Optional["BrowserManager"] = None):
        super().__init__("coupang_monitor", browser_manager)
        self._monitor_service = None
        self._api_client = None

    def _get_loop_interval(self) -> float:
        return self.LOOP_INTERVAL

    async def _initialize(self) -> None:
        """워커 초기화 — 서비스 인스턴스 생성 및 초기 스케줄 로드."""
        from app.modules.coupang_travel.services.api_client import CoupangApiClient
        from app.modules.coupang_travel.services.monitor_service import CoupangMonitorService
        from app.shared.notification import NotificationService
        from app.models.service_account import ServiceAccount

        self._api_client = CoupangApiClient()
        notification_service = NotificationService()
        self._monitor_service = CoupangMonitorService(self._api_client, notification_service)

        db = SessionLocal()
        try:
            account_count = (
                db.query(ServiceAccount)
                .filter(ServiceAccount.service_type == "coupang")
                .count()
            )
            active_schedules = schedule_service.get_all_with_context(
                db, is_enabled=True, service_type="coupang"
            )
            schedule_count = len(active_schedules)
        finally:
            db.close()

        logger.info(
            "[%s] 초기화 완료 — 서비스 계정 %d건, 활성 스케줄 %d건",
            self.name,
            account_count,
            schedule_count,
        )

    async def _main_loop_iteration(self) -> None:
        """메인 루프 1회 반복 — 활성 쿠팡 스케줄 순회 + 상태 체크."""
        if self._monitor_service is None:
            await self._initialize()

        # 활성 쿠팡 스케줄 조회
        db = SessionLocal()
        try:
            schedules = schedule_service.get_all_with_context(
                db, is_enabled=True, service_type="coupang"
            )
        finally:
            db.close()

        if not schedules:
            logger.debug("[%s] 활성 쿠팡 스케줄 없음, 스킵", self.name)
            return

        for ctx in schedules:
            await self._safe_execute(
                f"check_schedule_{ctx['id']}",
                lambda c=ctx: self._check_schedule(c),
            )

    async def _check_schedule(self, ctx: Dict) -> None:
        """단일 스케줄 상태 체크."""
        schedule_id = ctx.get("id")
        product_id = ctx.get("item_biz_item_id")
        date = ctx.get("date")
        service_account_id = ctx.get("service_account_id")

        if not product_id or not date:
            logger.warning("[%s] 스케줄 컨텍스트 불완전: %s", self.name, ctx.get("id"))
            return

        # extra_desc_json에서 vendor_item_package_id 파싱
        vendor_item_package_id = self._extract_vendor_item_package_id(ctx)
        if not vendor_item_package_id:
            logger.warning(
                "[%s] vendor_item_package_id 없음 (schedule_id=%s)",
                self.name,
                ctx.get("id"),
            )
            return

        if not self.browser:
            logger.warning("[%s] BrowserManager 없음", self.name)
            return

        active_marked = False
        try:
            self._set_schedule_active(schedule_id, True)
            active_marked = True

            context = await self.browser.get_context(service_account_id)
            pages = context.pages
            if pages:
                page = pages[0]
            else:
                page = await context.new_page()

            # 리퍼러 쿠키 세팅을 위해 상품 페이지로 이동 (이미 있으면 스킵)
            expected_url = f"https://trip.coupang.com/tp/products/{product_id}"
            if not page.url.startswith(expected_url):
                await page.goto(expected_url)

            changes = await self._monitor_service.check_and_notify(
                product_id=product_id,
                vendor_item_package_id=vendor_item_package_id,
                dates=[date],
                page=page,
                schedule_id=schedule_id,
            )

            if changes:
                logger.info(
                    "[%s] 상태 변경 %d건 감지 (product_id=%s, date=%s)",
                    self.name,
                    len(changes),
                    product_id,
                    date,
                )

        except Exception as e:
            logger.error(
                "[%s] 스케줄 체크 실패 (schedule_id=%s): %s",
                self.name,
                ctx.get("id"),
                e,
                exc_info=True,
            )
            raise
        finally:
            if active_marked:
                self._set_schedule_active(schedule_id, False)

    def _set_schedule_active(self, schedule_id: Optional[int], is_active: bool) -> None:
        """스케줄 active 상태를 DB에 반영."""
        if schedule_id is None:
            return
        db = SessionLocal()
        try:
            schedule_service.set_active(db, schedule_id, is_active)
        except Exception as e:
            logger.warning(
                "[%s] set_active 실패 (schedule_id=%s, is_active=%s): %s",
                self.name,
                schedule_id,
                is_active,
                e,
            )
        finally:
            db.close()

    def _extract_vendor_item_package_id(self, ctx: Dict) -> Optional[str]:
        """컨텍스트에서 vendor_item_package_id 추출."""
        # schedule_service._build_context_dict에는 extra_desc_json이 직접 없으므로
        # DB에서 별도로 읽어야 하지만, 간략화를 위해 BizItem에서 직접 읽음
        biz_item_pk = ctx.get("biz_item_pk")
        if not biz_item_pk:
            return None

        db = SessionLocal()
        try:
            from app.models.biz_item import BizItem
            item = db.query(BizItem).filter(BizItem.id == biz_item_pk).first()
            if not item or not item.extra_desc_json:
                return None
            extra = json.loads(item.extra_desc_json)
            return extra.get("vendor_item_package_id")
        except Exception as e:
            logger.error("[%s] extra_desc_json 파싱 실패: %s", self.name, e)
            return None
        finally:
            db.close()

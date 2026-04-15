"""
쿠팡 여행상품 취소표 모니터링 워커.

쿠팡 vendor-items API를 폴링하여 saleStatus/stockCount 변경 시 알림 발송.
네이버 워커와 독립적으로 동작하며 browser_manager를 공유합니다.

프록시 전략:
  1차: CoupangHttpClient (aiohttp + ProxyManager) — 브라우저 불필요, 요청 단위 로테이션
  2차: CoupangApiClient (Playwright fetch) — HTTP 전체 실패 시 fallback
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, TYPE_CHECKING

from sqlalchemy import text

from app.shared.worker.base_worker import BaseWorker
from app.database import SessionLocal
from app.services.schedule_service import ScheduleService

if TYPE_CHECKING:
    from app.shared.browser.browser_manager import BrowserManager
    from app.modules.coupang_travel.services.http_client import CoupangHttpClient

logger = logging.getLogger(__name__)

schedule_service = ScheduleService()


class CoupangMonitorWorker(BaseWorker):
    """쿠팡 여행상품 취소표 모니터링 워커."""

    LOOP_INTERVAL = 30.0  # 30초

    def __init__(self, browser_manager: Optional["BrowserManager"] = None):
        super().__init__("coupang_monitor", browser_manager)
        self._monitor_service = None
        self._api_client = None
        self._http_client: Optional["CoupangHttpClient"] = None
        self._popup_contexts: set = set()  # 팝업 차단 이벤트 등록된 context 추적

    def _get_loop_interval(self) -> float:
        return self.LOOP_INTERVAL

    async def _initialize(self) -> None:
        """워커 초기화 — 서비스 인스턴스 생성 및 초기 스케줄 로드."""
        from app.modules.coupang_travel.services.api_client import CoupangApiClient
        from app.modules.coupang_travel.services.monitor_service import CoupangMonitorService
        from app.modules.coupang_travel.services.http_client import CoupangHttpClient
        from app.shared.notification import NotificationService
        from app.models.service_account import ServiceAccount

        self._api_client = CoupangApiClient()
        notification_service = NotificationService()
        self._monitor_service = CoupangMonitorService(self._api_client, notification_service)

        # HTTP 클라이언트 초기화 (ProxyManager 연동)
        proxy_manager = self._get_proxy_manager()
        proxy_usage_logger = self._get_proxy_usage_logger()
        self._http_client = CoupangHttpClient(
            proxy_manager=proxy_manager,
            proxy_usage_logger=proxy_usage_logger,
        )
        if proxy_manager:
            logger.info("[%s] HTTP 클라이언트 초기화 완료 (프록시 활성)", self.name)
        else:
            logger.info("[%s] HTTP 클라이언트 초기화 완료 (프록시 없음, 직접 연결)", self.name)

        stale_active_count = self._cleanup_stale_active_schedules()

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
        if stale_active_count:
            logger.info(
                "[%s] stale is_active 스케줄 %d건 정리 완료",
                self.name,
                stale_active_count,
            )

    def _get_proxy_manager(self):
        """ProxyManager 싱글톤 획득 (없으면 None)."""
        try:
            from app.services.proxy_manager_factory import get_proxy_manager
            return get_proxy_manager()
        except Exception:
            return None

    def _get_proxy_usage_logger(self):
        """ProxyUsageLogger 싱글톤 획득 (없으면 None)."""
        try:
            from app.services.proxy_usage_logger import get_proxy_usage_logger
            return get_proxy_usage_logger()
        except Exception:
            return None

    def _cleanup_stale_active_schedules(self) -> int:
        """워커 시작 시점에 남아 있는 coupang 활성 플래그를 정리합니다."""
        db = SessionLocal()
        try:
            result = db.execute(text("""
                UPDATE monitor_schedules
                SET is_active = false,
                    run_status = 'idle'
                WHERE is_active = true
                  AND biz_item_id IN (
                    SELECT bi.id
                    FROM biz_items bi
                    JOIN businesses b ON bi.business_id = b.id
                    WHERE b.service_type = 'coupang'
                  )
            """))
            db.commit()
            return result.rowcount or 0
        except Exception as e:
            db.rollback()
            logger.warning("[%s] stale active schedule cleanup 실패: %s", self.name, e, exc_info=True)
            return 0
        finally:
            db.close()

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
        """단일 스케줄 상태 체크. HTTP 클라이언트 우선, 실패 시 Playwright fallback."""
        schedule_id = ctx.get("id")
        product_id = ctx.get("item_biz_item_id")
        date = ctx.get("date")
        service_account_id = ctx.get("service_account_id")

        if not product_id or not date:
            logger.warning("[%s] 스케줄 컨텍스트 불완전: %s", self.name, ctx.get("id"))
            return

        vendor_item_package_id = self._extract_vendor_item_package_id(ctx)
        if not vendor_item_package_id:
            logger.warning(
                "[%s] vendor_item_package_id 없음 (schedule_id=%s)",
                self.name,
                ctx.get("id"),
            )
            return

        active_marked = False
        checked_at: Optional[datetime] = None
        try:
            self._set_schedule_active(schedule_id, True)
            active_marked = True

            notify_times = ctx.get("times")

            # 1차 시도: HTTP 클라이언트 (aiohttp + 프록시 로테이션)
            changes, checked_at = await self._check_via_http(
                product_id=product_id,
                vendor_item_package_id=vendor_item_package_id,
                date=date,
                schedule_id=schedule_id,
                notify_times=notify_times,
            )
            if checked_at is None:
                checked_at = datetime.now()

            # HTTP 실패 시 2차: Playwright fallback
            if changes is None:
                logger.warning(
                    "[%s] HTTP 클라이언트 실패 — Playwright fallback 시도 (schedule_id=%s)",
                    self.name, schedule_id,
                )
                changes, checked_at = await self._check_via_playwright(
                    product_id=product_id,
                    vendor_item_package_id=vendor_item_package_id,
                    date=date,
                    schedule_id=schedule_id,
                    service_account_id=service_account_id,
                    notify_times=notify_times,
                )
                if checked_at is None:
                    checked_at = datetime.now()

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
            if schedule_id is not None:
                self._set_schedule_last_check_time(
                    schedule_id,
                    checked_at or datetime.now(),
                )

    async def _check_via_http(
        self,
        product_id: str,
        vendor_item_package_id: str,
        date: str,
        schedule_id: Optional[int],
        notify_times: Optional[List] = None,
    ) -> tuple[Optional[List], Optional[datetime]]:
        """
        HTTP 클라이언트(aiohttp + 프록시)로 상태 체크.

        Returns:
            (StatusChange 목록 (성공), None), 체크 시각
        """
        if self._http_client is None:
            return None, None

        started_at = time.perf_counter()
        items = await self._http_client.fetch_vendor_items(
            product_id=product_id,
            vendor_item_package_id=vendor_item_package_id,
            select_date=date,
            schedule_id=schedule_id,
        )
        response_time_ms = (time.perf_counter() - started_at) * 1000
        checked_at = datetime.now()

        if items is None:
            return None, checked_at  # HTTP 실패 → caller가 fallback 처리

        changes = await self._monitor_service.check_and_notify(
            product_id=product_id,
            vendor_item_package_id=vendor_item_package_id,
            dates=[date],
            prefetched_items=items,
            prefetched_response_time_ms=response_time_ms,
            prefetched_checked_at=checked_at,
            schedule_id=schedule_id,
            notify_times=notify_times,
        )
        return changes, checked_at

    async def _check_via_playwright(
        self,
        product_id: str,
        vendor_item_package_id: str,
        date: str,
        schedule_id: Optional[int],
        service_account_id: Optional[int],
        notify_times: Optional[List] = None,
    ) -> tuple[Optional[List], Optional[datetime]]:
        """
        Playwright 브라우저로 상태 체크 (HTTP 실패 시 fallback).

        Returns:
            (StatusChange 목록 (성공), None (BrowserManager 없거나 실패), 체크 시각)
        """
        if not self.browser:
            logger.warning("[%s] BrowserManager 없음 — Playwright fallback 불가", self.name)
            return None, None

        if not self.browser.tab_pool_manager:
            logger.warning("[%s] TabPoolManager 없음 — Playwright fallback 불가", self.name)
            return None, None

        page = None
        try:
            page = await self.browser.tab_pool_manager.get_tab(schedule_id, service_account_id)

            # 팝업 차단: 쿠팡 사이트 JS가 window.open()으로 여는 탭 자동 닫기
            context = page.context
            if context not in self._popup_contexts:
                async def _on_popup(popup):
                    await popup.close()
                context.on("page", _on_popup)
                self._popup_contexts.add(context)

            expected_url = f"https://trip.coupang.com/tp/products/{product_id}"
            if not page.url.startswith(expected_url):
                await page.goto(expected_url)

            changes = await self._monitor_service.check_and_notify(
                product_id=product_id,
                vendor_item_package_id=vendor_item_package_id,
                dates=[date],
                page=page,
                schedule_id=schedule_id,
                notify_times=notify_times,
            )
            return changes, datetime.now()
        finally:
            if page is not None:
                await self.browser.tab_pool_manager.release_tab(page)

    def _set_schedule_last_check_time(self, schedule_id: int, checked_at: datetime) -> None:
        """스케줄 마지막 확인 시각 저장."""
        if schedule_id is None:
            return
        db = SessionLocal()
        try:
            schedule_service.set_last_check_time(db, schedule_id, checked_at)
        except Exception as e:
            logger.warning(
                "[%s] schedule last_check_time 갱신 실패 (schedule_id=%s): %s",
                self.name,
                schedule_id,
                e,
            )
        finally:
            db.close()

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

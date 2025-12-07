"""
BrowserService - 브라우저 서비스 파사드 (리팩토링됨)

기존 BrowserService의 인터페이스를 유지하면서
내부 구현을 분리된 모듈들에 위임합니다.

하위 호환성:
- from app.services.browser_service import BrowserService
- from app.services.browser import BrowserService
"""

import asyncio
import time
from datetime import datetime
from typing import Dict, Optional, Tuple, Union

from playwright.async_api import BrowserContext, Page
from sqlalchemy import text

from app.config import settings, logger
from app.database import SessionLocal
from app.services.notification_service import NotificationService
from app.services.naver_site_monitor import NaverSiteMonitor
from app.services.schedule_monitor_service import get_schedule_monitor_service

from .context_manager import ContextManager
from .tab_pool_manager import TabPoolManager
from .resource_monitor import ResourceMonitor
from .monitoring_executor import MonitoringExecutor
from .monitoring_queue import MonitoringQueue


class BrowserService:
    """
    BrowserService - 브라우저 서비스 파사드

    리팩토링된 모듈들을 조합하여 기존 인터페이스를 유지합니다.
    """

    def __init__(self):
        """BrowserService 초기화"""
        # 서비스 초기화
        self.schedule_service = get_schedule_monitor_service()
        self.notification_service = NotificationService()

        # 컨텍스트 관리자 초기화
        self._context_manager = ContextManager()

        # 탭 풀 관리자 초기화
        self._tab_pool_manager = TabPoolManager(self._context_manager)

        # 리소스 모니터 초기화
        self._resource_monitor = ResourceMonitor(self._tab_pool_manager)

        # 네이버 사이트 모니터 초기화 (self 전달로 순환 참조 해결)
        self.naver_site_monitor = NaverSiteMonitor(browser_service=self)

        # 모니터링 실행자 초기화
        self._monitoring_executor = MonitoringExecutor(
            self._tab_pool_manager,
            self.schedule_service,
            self.notification_service,
            self.naver_site_monitor
        )

        # 모니터링 대기열 초기화
        self._monitoring_queue = MonitoringQueue(
            self._tab_pool_manager,
            self._monitoring_executor,
            self.schedule_service
        )

        # 전역 일시중지 상태 캐싱
        self._global_pause_cache = False
        self._global_pause_cache_time = 0
        self._global_pause_cache_ttl = 2

        logger.info("브라우저 서비스 초기화 완료 (다중 프로필 지원)")

    # =========================================================================
    # 컨텍스트 관리 프로퍼티 (하위 호환성)
    # =========================================================================

    @property
    def browser_context(self) -> Optional[BrowserContext]:
        """기본 브라우저 컨텍스트 (하위 호환성)"""
        return self._context_manager.browser_context

    @browser_context.setter
    def browser_context(self, value: Optional[BrowserContext]):
        """기본 브라우저 컨텍스트 설정"""
        self._context_manager.browser_context = value

    @property
    def browser_contexts(self) -> Dict[int, BrowserContext]:
        """계정별 브라우저 컨텍스트 딕셔너리"""
        return self._context_manager.browser_contexts

    @browser_contexts.setter
    def browser_contexts(self, value: Dict[int, BrowserContext]):
        """계정별 브라우저 컨텍스트 설정 (테스트용)"""
        self._context_manager.browser_contexts = value

    @property
    def playwright_instance(self):
        """Playwright 인스턴스"""
        return self._context_manager.playwright_instance

    @playwright_instance.setter
    def playwright_instance(self, value):
        """Playwright 인스턴스 설정"""
        self._context_manager.playwright_instance = value

    # =========================================================================
    # 탭 풀 프로퍼티 (하위 호환성)
    # =========================================================================

    @property
    def tab_pool(self) -> Dict[str, Page]:
        """전역 탭 풀 (하위 호환성)"""
        return self._tab_pool_manager.tab_pool

    @property
    def tab_pools(self) -> Dict[int, Dict[str, Page]]:
        """계정별 탭 풀"""
        return self._tab_pool_manager.tab_pools

    @property
    def tab_last_used(self) -> Dict[str, float]:
        """탭 마지막 사용 시간"""
        return self._tab_pool_manager.tab_last_used

    @property
    def tab_in_use(self) -> Dict[str, bool]:
        """탭 사용 중 상태"""
        return self._tab_pool_manager.tab_in_use

    @property
    def tab_use_count(self) -> Dict[str, int]:
        """탭 사용 횟수"""
        return self._tab_pool_manager.tab_use_count

    @property
    def tab_current_target(self) -> Dict[str, int]:
        """탭 현재 대상"""
        return self._tab_pool_manager.tab_current_target

    @property
    def tab_account(self) -> Dict[str, int]:
        """탭이 속한 계정"""
        return self._tab_pool_manager.tab_account

    @property
    def TOTAL_MAX_TABS(self) -> int:
        """전체 최대 탭 수"""
        return self._tab_pool_manager.TOTAL_MAX_TABS

    @TOTAL_MAX_TABS.setter
    def TOTAL_MAX_TABS(self, value: int):
        """전체 최대 탭 수 설정 (테스트용)"""
        self._tab_pool_manager.TOTAL_MAX_TABS = value

    @property
    def TAB_REQUEST_TIMEOUT(self) -> int:
        """탭 요청 타임아웃"""
        return self._tab_pool_manager.TAB_REQUEST_TIMEOUT

    @TAB_REQUEST_TIMEOUT.setter
    def TAB_REQUEST_TIMEOUT(self, value: int):
        """탭 요청 타임아웃 설정 (테스트용)"""
        self._tab_pool_manager.TAB_REQUEST_TIMEOUT = value

    @property
    def MAX_USES_PER_TAB(self) -> int:
        """탭당 최대 사용 횟수"""
        return self._tab_pool_manager.MAX_USES_PER_TAB

    @property
    def total_active_tabs(self) -> int:
        """전체 활성 탭 수"""
        return self._tab_pool_manager.total_active_tabs

    # =========================================================================
    # 리소스 모니터 프로퍼티 (하위 호환성)
    # =========================================================================

    @property
    def memory_stats(self) -> Dict[int, Dict]:
        """메모리 통계"""
        return self._resource_monitor.memory_stats

    @property
    def MEMORY_THRESHOLD_MB(self) -> int:
        """메모리 임계값"""
        return self._resource_monitor.MEMORY_THRESHOLD_MB

    @MEMORY_THRESHOLD_MB.setter
    def MEMORY_THRESHOLD_MB(self, value: int):
        """메모리 임계값 설정 (테스트용)"""
        self._resource_monitor.MEMORY_THRESHOLD_MB = value

    @property
    def last_memory_check(self) -> float:
        """마지막 메모리 체크 시간"""
        return self._resource_monitor.last_memory_check

    @last_memory_check.setter
    def last_memory_check(self, value: float):
        """마지막 메모리 체크 시간 설정 (테스트용)"""
        self._resource_monitor.last_memory_check = value

    @property
    def resource_cleanup_task(self):
        """리소스 정리 태스크"""
        return self._resource_monitor.resource_cleanup_task

    @resource_cleanup_task.setter
    def resource_cleanup_task(self, value):
        """리소스 정리 태스크 설정"""
        self._resource_monitor.resource_cleanup_task = value

    # =========================================================================
    # 모니터링 프로퍼티 (하위 호환성)
    # =========================================================================

    @property
    def monitoring_tasks(self) -> Dict[int, asyncio.Task]:
        """모니터링 태스크 딕셔너리"""
        return self._monitoring_queue.monitoring_tasks

    @property
    def url_states(self) -> Dict[str, Dict]:
        """URL 상태 딕셔너리"""
        return self._monitoring_executor.url_states

    # =========================================================================
    # 전역 일시중지 상태
    # =========================================================================

    def is_global_paused(self) -> bool:
        """전역 모니터링 일시중지 상태를 확인합니다 (캐시 사용)."""
        current_time = time.time()
        if current_time - self._global_pause_cache_time > self._global_pause_cache_ttl:
            try:
                db = SessionLocal()
                try:
                    result = db.execute(text(
                        "SELECT global_pause FROM worker_status WHERE id = 1"
                    )).fetchone()
                    self._global_pause_cache = bool(result[0]) if result and result[0] is not None else False
                    self._global_pause_cache_time = current_time
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"전역 일시중지 상태 확인 오류: {str(e)}")
        return self._global_pause_cache

    # =========================================================================
    # 초기화 메서드
    # =========================================================================

    async def initialize(self):
        """브라우저 서비스의 비동기 초기화를 수행합니다."""
        logger.info("BrowserService.initialize() 메소드 시작")

        # 브라우저 초기화
        await self.initialize_browser()

        # 브라우저 컨텍스트 검증
        if self.browser_context is None:
            raise RuntimeError("브라우저 컨텍스트 초기화 실패: browser_context가 None입니다")

        try:
            pages = self.browser_context.pages
            logger.info(f"브라우저 초기화 검증 완료: 현재 페이지 수 {len(pages)}")
        except Exception as e:
            raise RuntimeError(f"브라우저 컨텍스트 검증 실패: {str(e)}")

        # 리소스 정리 태스크 시작
        await self.start_resource_monitoring_async()
        logger.info("BrowserService.initialize() 메소드 완료")
        return self

    async def start_resource_monitoring_async(self):
        """리소스 모니터링 및 정리 태스크를 비동기적으로 시작합니다."""
        await self._resource_monitor.start_resource_monitoring_async()

    def start_resource_monitoring(self):
        """리소스 모니터링 및 정리 태스크를 시작합니다."""
        self._resource_monitor.start_resource_monitoring()

    # =========================================================================
    # 컨텍스트 관리 메서드 (ContextManager에 위임)
    # =========================================================================

    async def initialize_browser(self) -> BrowserContext:
        """단일 브라우저 컨텍스트를 초기화합니다."""
        return await self._context_manager.initialize_browser()

    async def ensure_browser(self) -> BrowserContext:
        """브라우저 컨텍스트가 없으면 초기화합니다."""
        if self.browser_context is None:
            return await self.initialize_browser()
        return self.browser_context

    async def get_or_create_context(self, account_id: Optional[int] = None) -> BrowserContext:
        """계정별 브라우저 컨텍스트를 가져오거나 생성합니다."""
        return await self._context_manager.get_or_create_context(account_id)

    async def _create_browser_context(self, account_id: int) -> BrowserContext:
        """계정별 브라우저 컨텍스트를 생성합니다."""
        return await self._context_manager._create_browser_context(account_id)

    async def _create_browser_context_visible(self, account_id: int) -> BrowserContext:
        """계정별 브라우저 컨텍스트를 headless=False로 생성합니다."""
        return await self._context_manager._create_browser_context_visible(account_id)

    async def close_context(self, account_id: int):
        """특정 계정의 브라우저 컨텍스트를 닫습니다."""
        await self._context_manager.close_context(account_id)

    async def close_all_contexts(self):
        """모든 브라우저 컨텍스트를 닫습니다."""
        await self._context_manager.close_all_contexts()

    async def _bypass_automation_detection(self, context: BrowserContext):
        """자동화 감지를 우회하기 위한 스크립트를 주입합니다."""
        await self._context_manager._bypass_automation_detection(context)

    async def move_window_to_center(self) -> bool:
        """브라우저 창을 화면 중앙으로 이동합니다."""
        return await self._context_manager.move_window_to_center()

    async def move_window_to_corner(self) -> bool:
        """브라우저 창을 화면 우측 하단 구석으로 이동합니다."""
        return await self._context_manager.move_window_to_corner()

    # =========================================================================
    # 탭 풀 관리 메서드 (TabPoolManager에 위임)
    # =========================================================================

    async def get_tab(self, target_id: int, account_id: Optional[int] = None) -> Page:
        """계정별 탭 풀에서 사용 가능한 탭을 가져오거나 새로 생성합니다."""
        return await self._tab_pool_manager.get_tab(target_id, account_id)

    async def release_tab(self, tab: Page):
        """탭 사용을 완료하고 풀로 반환합니다."""
        await self._tab_pool_manager.release_tab(tab)

    async def cleanup_old_tabs(self, force_cleanup: bool = False):
        """오래된 탭을 정리합니다."""
        return await self._tab_pool_manager.cleanup_old_tabs(force_cleanup)

    async def _is_tab_closed(self, tab: Page) -> bool:
        """탭이 닫혔는지 확인합니다."""
        return await self._tab_pool_manager._is_tab_closed(tab)

    async def _remove_tab_from_pool(self, tab_id: str, account_id: int):
        """탭 풀에서 탭을 제거합니다."""
        await self._tab_pool_manager._remove_tab_from_pool(tab_id, account_id)

    async def _handle_browser_closed_error(self, account_id: int):
        """브라우저가 닫혔을 때 해당 계정의 컨텍스트와 탭을 정리합니다."""
        await self._tab_pool_manager.handle_browser_closed_error(account_id)

    # =========================================================================
    # 리소스 모니터링 메서드 (ResourceMonitor에 위임)
    # =========================================================================

    async def monitor_resources(self):
        """리소스 사용량을 모니터링하고 필요시 정리합니다."""
        await self._resource_monitor.monitor_resources()

    async def check_memory(self):
        """전역 메모리 사용량을 확인하고 필요시 정리합니다."""
        await self._resource_monitor.check_memory()

    async def cleanup_resources(self):
        """전역 탭 풀 리소스를 정리합니다."""
        await self._resource_monitor.cleanup_resources()

    async def perform_global_cleanup(self):
        """전역 탭 풀 정리를 수행합니다."""
        await self._resource_monitor.perform_global_cleanup()

    # =========================================================================
    # 모니터링 실행 메서드 (MonitoringExecutor에 위임)
    # =========================================================================

    async def load_page(self, tab: Page, url: str) -> Tuple[Union[str, None], Union[str, None], Union[str, None]]:
        """페이지를 로드하고 콘텐츠를 반환합니다."""
        return await self._monitoring_executor.load_page(tab, url)

    async def perform_monitoring(self, tab: Page, url: str, target_id: int, label: str, target=None) -> bool:
        """실제 모니터링을 수행합니다."""
        return await self._monitoring_executor.perform_monitoring(tab, url, target_id, label, target)

    async def _perform_naver_monitoring(self, tab: Page, url: str, target_id: int, label: str, target=None) -> bool:
        """네이버 예약 Fetch 방식 모니터링"""
        return await self._monitoring_executor._perform_naver_monitoring(tab, url, target_id, label, target)

    async def _perform_html_monitoring(self, tab: Page, url: str, target_id: int, label: str) -> bool:
        """기존 HTML 해시 방식 모니터링"""
        return await self._monitoring_executor._perform_html_monitoring(tab, url, target_id, label)

    async def handle_change(self, target_id: int, url: str, label: str, content: str, last_check_time: datetime):
        """변경 사항을 처리합니다."""
        await self._monitoring_executor.handle_change(target_id, url, label, content, last_check_time)

    def _calculate_next_run_time(self, target) -> float:
        """다음 실행 시간을 계산합니다."""
        return self._monitoring_executor.calculate_next_run_time(target)

    # =========================================================================
    # 모니터링 대기열 메서드 (MonitoringQueue에 위임)
    # =========================================================================

    async def start_monitoring(self, data: dict):
        """새로운 모니터링을 시작합니다."""
        return await self._monitoring_queue.start_monitoring(data)

    async def stop_monitoring(self, target_id: int) -> bool:
        """모니터링을 중지합니다."""
        return await self._monitoring_queue.stop_monitoring(target_id)

    async def add_to_monitoring_queue(self, target_data: dict):
        """모니터링 대상을 대기열에 추가합니다."""
        await self._monitoring_queue.add_to_monitoring_queue(target_data)

    async def _process_monitoring_queue(self):
        """대기열에 있는 모니터링 작업을 처리합니다."""
        await self._monitoring_queue._process_monitoring_queue()

    async def _check_queue_after_task_completion(self):
        """태스크 완료 후 대기열에서 다음 항목을 처리할 수 있는지 확인합니다."""
        await self._monitoring_queue._check_queue_after_task_completion()

    async def process_initial_queue(self, max_items: int):
        """대기열에서 지정된 수만큼 항목을 꺼내서 처리합니다."""
        await self._monitoring_queue.process_initial_queue(max_items)

    async def monitor_url(self, target_id: int, url: str, label: str):
        """URL을 모니터링합니다."""
        await self._monitoring_queue._monitor_url(target_id, url, label)

    # =========================================================================
    # 계정 세션 관리 메서드
    # =========================================================================

    async def open_browser_for_account(self, account_id: int, url: Optional[str] = None) -> Dict:
        """특정 계정의 브라우저를 열고 선택적으로 URL로 이동합니다.

        기존 컨텍스트가 있으면 재사용하고 창을 포커스합니다.
        """
        from app.services.account_service import account_service

        db = SessionLocal()
        try:
            account = account_service.get_by_id(db, account_id)
            if not account:
                return {"success": False, "message": f"계정 {account_id}를 찾을 수 없습니다"}

            # 기존 컨텍스트 확인
            existing_context = self._context_manager.browser_contexts.get(account_id)
            if existing_context:
                try:
                    pages = existing_context.pages
                    if pages:
                        # 기존 창을 화면 중앙으로 이동하고 포커스
                        page = pages[0]
                        try:
                            cdp = await page.context.new_cdp_session(page)
                            window_info = await cdp.send("Browser.getWindowForTarget")
                            window_id = window_info.get("windowId")
                            if window_id:
                                await cdp.send("Browser.setWindowBounds", {
                                    "windowId": window_id,
                                    "bounds": {
                                        "left": 560,
                                        "top": 240,
                                        "width": 1280,
                                        "height": 800,
                                        "windowState": "normal"
                                    }
                                })
                            await page.bring_to_front()
                            logger.info(f"계정 {account_id} 기존 브라우저 창을 포커스했습니다")
                        except Exception as e:
                            logger.warning(f"창 포커스 실패, 새 탭으로 이동: {e}")

                        # URL이 지정된 경우 해당 URL로 이동
                        if url:
                            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                            logger.info(f"계정 {account_id} 브라우저가 {url}로 이동했습니다")

                        return {
                            "success": True,
                            "message": f"기존 브라우저 창을 포커스했습니다",
                            "account_id": account_id,
                            "account_name": account.name,
                            "url": url or page.url
                        }
                except Exception:
                    # 컨텍스트가 닫혀있으면 딕셔너리에서 제거
                    del self._context_manager.browser_contexts[account_id]
                    logger.info(f"계정 {account_id} 컨텍스트가 닫혀있어 새로 생성합니다")

            # 기존 컨텍스트가 없으면 새로 생성
            context = await self._create_browser_context_visible(account_id)
            page = await context.new_page()

            if url:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                logger.info(f"계정 {account_id} 브라우저가 {url}로 이동했습니다")
            else:
                logger.info(f"계정 {account_id} 브라우저가 열렸습니다 (빈 페이지)")

            return {
                "success": True,
                "message": f"브라우저가 열렸습니다",
                "account_id": account_id,
                "account_name": account.name,
                "url": url or "about:blank"
            }

        except Exception as e:
            logger.error(f"브라우저 열기 실패 (account_id={account_id}): {str(e)}")
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    async def open_naver_login(self, account_id: int) -> Dict:
        """특정 계정의 브라우저를 열고 네이버 로그인 페이지로 이동합니다."""
        naver_login_url = "https://nid.naver.com/nidlogin.login"
        return await self.open_browser_for_account(account_id, naver_login_url)

    async def check_naver_login_status(self, account_id: int) -> Dict:
        """특정 계정의 네이버 로그인 상태를 확인합니다."""
        from app.services.account_service import account_service

        db = SessionLocal()
        try:
            account = account_service.get_by_id(db, account_id)
            if not account:
                return {"success": False, "message": f"계정 {account_id}를 찾을 수 없습니다", "is_logged_in": False}

            context = await self._create_browser_context_visible(account_id)
            page = await context.new_page()

            try:
                await page.goto("https://www.naver.com", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(1)

                is_logged_in = False
                page_content = await page.content()

                if "로그인" in page_content:
                    login_link = await page.query_selector('a[href*="nidlogin"]')
                    if login_link:
                        login_text = await login_link.inner_text()
                        if "로그인" in login_text:
                            is_logged_in = False
                        else:
                            is_logged_in = True
                    else:
                        is_logged_in = True
                else:
                    is_logged_in = True

                try:
                    user_selectors = [
                        '.MyView-module__my_area___QlLak',
                        '.MyView-module__link_name',
                        '#account',
                        '.gnb_my'
                    ]
                    for selector in user_selectors:
                        user_elem = await page.query_selector(selector)
                        if user_elem:
                            is_logged_in = True
                            break
                except:
                    pass

                account_service.update_login_status(db, account_id, is_logged_in)

                logger.info(f"계정 {account_id} 로그인 상태 확인: {'로그인됨' if is_logged_in else '로그아웃'}")

                return {
                    "success": True,
                    "account_id": account_id,
                    "account_name": account.name,
                    "is_logged_in": is_logged_in,
                    "message": "로그인됨" if is_logged_in else "로그인 필요"
                }

            finally:
                await page.close()

        except Exception as e:
            logger.error(f"로그인 상태 확인 실패 (account_id={account_id}): {str(e)}")
            return {"success": False, "message": str(e), "is_logged_in": False}
        finally:
            db.close()

    async def close_browser_session(self, account_id: int) -> Dict:
        """특정 계정의 브라우저 세션을 종료합니다."""
        from app.services.account_service import account_service

        db = SessionLocal()
        try:
            account = account_service.get_by_id(db, account_id)
            account_name = account.name if account else f"ID:{account_id}"

            if account_id not in self.browser_contexts:
                return {
                    "success": True,
                    "message": f"열려있는 브라우저 세션이 없습니다",
                    "account_id": account_id,
                    "account_name": account_name
                }

            await self.close_context(account_id)

            logger.info(f"계정 {account_id} 브라우저 세션 종료 완료")

            return {
                "success": True,
                "message": "브라우저 세션이 종료되었습니다",
                "account_id": account_id,
                "account_name": account_name
            }

        except Exception as e:
            logger.error(f"브라우저 세션 종료 실패 (account_id={account_id}): {str(e)}")
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    def get_active_sessions(self) -> Dict:
        """현재 활성화된 브라우저 세션 목록을 반환합니다."""
        return {
            "active_sessions": list(self.browser_contexts.keys()),
            "count": len(self.browser_contexts)
        }


# ============================================================
# 싱글톤 인스턴스 관리
# ============================================================

_browser_service_instance: Optional[BrowserService] = None


def get_browser_service() -> BrowserService:
    """
    BrowserService 싱글톤 인스턴스를 반환합니다.
    API 라우트와 Worker에서 동일한 인스턴스를 공유하기 위해 사용합니다.
    """
    global _browser_service_instance
    if _browser_service_instance is None:
        _browser_service_instance = BrowserService()
        logger.info("BrowserService 싱글톤 인스턴스 생성")
    return _browser_service_instance


def set_browser_service(instance: BrowserService):
    """
    BrowserService 싱글톤 인스턴스를 설정합니다.
    Worker에서 생성한 인스턴스를 공유하기 위해 사용합니다.
    """
    global _browser_service_instance
    _browser_service_instance = instance
    logger.info("BrowserService 싱글톤 인스턴스 설정됨")

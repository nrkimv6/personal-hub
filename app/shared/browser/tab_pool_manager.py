"""
탭 풀 관리 모듈

브라우저 탭의 생성, 할당, 반환, 정리를 담당합니다.
"""

import asyncio
import time
import random
from typing import Dict, Optional, TYPE_CHECKING

from playwright.async_api import Page, BrowserContext

from app.core.config import settings, logger

if TYPE_CHECKING:
    from .context_manager import ContextManager


class TabPoolManager:
    """탭 풀 관리자"""

    def __init__(self, context_manager: "ContextManager"):
        """
        TabPoolManager 초기화

        Args:
            context_manager: 브라우저 컨텍스트 관리자
        """
        self.context_manager = context_manager

        # 계정별 탭 풀 (account_id별로 분리)
        self.tab_pools: Dict[int, Dict[str, Page]] = {}
        self.tab_pool: Dict[str, Page] = {}  # 하위 호환성
        self.tab_last_used: Dict[str, float] = {}
        self.tab_in_use: Dict[str, bool] = {}
        self.tab_use_count: Dict[str, int] = {}
        self.tab_current_target: Dict[str, int] = {}
        self.tab_account: Dict[str, int] = {}

        # 탭 요청 대기열 (전역)
        self.tab_waiters: Dict[str, asyncio.Event] = {}

        # 탭 관리 설정
        self.TAB_ROTATION_THRESHOLD = settings.TAB_ROTATION_THRESHOLD
        self.CACHE_CLEANUP_INTERVAL = settings.CACHE_CLEANUP_INTERVAL
        self.TAB_REQUEST_TIMEOUT = settings.TAB_REQUEST_TIMEOUT
        self.TAB_WAIT_RETRY_INTERVAL = settings.TAB_WAIT_RETRY_INTERVAL
        self.TOTAL_MAX_TABS = settings.TOTAL_MAX_TABS
        self.MAX_USES_PER_TAB = settings.MAX_USES_PER_TAB

        # 전체 현재 활성 탭 수 추적
        self.total_active_tabs = 0

        # 계정별 브라우저 복구 진행 중 플래그 (race condition 방지)
        self._recovery_in_progress: Dict[int, bool] = {}

    async def get_tab(self, target_id: int, service_account_id: Optional[int] = None) -> Page:
        """계정별 탭 풀에서 사용 가능한 탭을 가져오거나 새로 생성합니다.

        Args:
            target_id: 모니터링 대상 (스케줄) ID
            service_account_id: 계정 ID (None이면 기본 계정 사용)

        Returns:
            Page: 해당 계정의 브라우저 컨텍스트에서 생성된 탭
        """
        # account_id가 None이면 기본 계정(id=1) 사용
        if service_account_id is None:
            service_account_id = 1

        # 해당 계정의 브라우저 컨텍스트 가져오기 또는 생성
        context = await self.context_manager.get_or_create_context(service_account_id)

        # 컨텍스트 유효성 확인
        context_valid = False
        try:
            pages = context.pages
            # 추가로 실제 접근 가능한지 확인
            if len(pages) > 0:
                # 첫 번째 페이지로 간단한 테스트
                try:
                    _ = pages[0].url
                    context_valid = True
                except Exception as e:
                    logger.warning(f"페이지 접근 실패 (service_account_id={service_account_id}): {e}")
            else:
                # 페이지가 없으면 브라우저가 살아있는지 직접 확인
                try:
                    browser = context.browser
                    if browser and browser.is_connected():
                        context_valid = True
                    else:
                        logger.warning(f"브라우저 연결 끊김 (service_account_id={service_account_id})")
                except Exception as e:
                    logger.warning(f"브라우저 연결 상태 확인 실패 (service_account_id={service_account_id}): {e}")
        except Exception as e:
            logger.warning(f"브라우저 컨텍스트가 닫힘 (service_account_id={service_account_id}): {str(e)}")

        if not context_valid:
            logger.warning(f"브라우저 컨텍스트 재생성 필요 (service_account_id={service_account_id})")

            # handle_browser_closed_error를 통해 Lock 획득 후 정리 및 재생성 (race condition 방지)
            cleanup_performed = await self.handle_browser_closed_error(service_account_id, recreate=True)

            if cleanup_performed:
                logger.info(f"브라우저 컨텍스트 재생성 완료 (service_account_id={service_account_id})")
            else:
                # 다른 태스크가 복구 중이면, get_or_create_context로 대기 후 기존 컨텍스트 사용
                logger.info(f"다른 태스크에서 복구 중, 컨텍스트 대기 (service_account_id={service_account_id})")

            # 재생성된 컨텍스트 가져오기
            context = await self.context_manager.get_or_create_context(service_account_id)

        # 계정별 탭 풀 초기화 및 초기 빈 탭 등록
        if service_account_id not in self.tab_pools:
            self.tab_pools[service_account_id] = {}
            # 새 컨텍스트의 초기 빈 탭 등록 (launch_persistent_context로 생성된 탭 재사용)
            await self.register_initial_tabs(service_account_id, context)

        account_tab_pool = self.tab_pools[service_account_id]

        # 고유 요청 ID 생성
        request_id = f"req_{int(time.time())}_{random.randint(1000, 9999)}"

        # 오래된 탭 정리
        await self.cleanup_old_tabs()

        # 탭 획득 시도 시작
        start_time = time.time()
        wait_count = 0
        max_wait_time = self.TAB_REQUEST_TIMEOUT

        # 전체 탭 수 계산 (모든 계정의 탭 합계)
        total_tabs = sum(len(pool) for pool in self.tab_pools.values())

        while True:
            # 시간 초과 확인
            if time.time() - start_time > max_wait_time:
                logger.warning(f"대상 {target_id}의 탭 요청이 {max_wait_time}초를 초과하여 시간 초과 (service_account_id={service_account_id})")
                raise TimeoutError(f"탭 요청 시간 초과 (대상 ID: {target_id}, 계정 ID: {service_account_id}, 요청 ID: {request_id})")

            # 해당 계정의 사용 가능한 탭 찾기 (사용 중이 아니고, 사용 횟수 미달)
            available_tabs = [
                tab_id for tab_id in account_tab_pool.keys()
                if not self.tab_in_use.get(tab_id, False)
                and self.tab_use_count.get(tab_id, 0) < self.MAX_USES_PER_TAB
            ]

            if available_tabs:
                # 사용 가능한 탭 중 가장 최근 사용된 탭 선택 (캐시 활용)
                tab_id = max(available_tabs, key=lambda tid: self.tab_last_used.get(tid, 0))
                tab = account_tab_pool[tab_id]

                # ★ 즉시 탭 잠금 (다른 코루틴이 같은 탭을 선택하지 못하도록)
                self.tab_in_use[tab_id] = True

                # 탭 유효성 검사 - 닫혔으면 풀에서 제거하고 다시 시도
                if await self._is_tab_closed(tab):
                    logger.warning(f"탭 {tab_id}이 닫혀있어 풀에서 제거합니다 (service_account_id={service_account_id})")
                    self.tab_in_use[tab_id] = False  # 잠금 해제
                    await self._remove_tab_from_pool(tab_id, service_account_id)
                    continue

                tabs_in_use = sum(1 for in_use in self.tab_in_use.values() if in_use)
                logger.info(f"🔒 탭 획득: {tab_id} → 대상 {target_id} (사용 중: {tabs_in_use}/{self.TOTAL_MAX_TABS})")
                break

            # 새 탭 생성 가능 여부 확인 (전체 최대 탭 수 기준)
            total_tabs = sum(len(pool) for pool in self.tab_pools.values())
            if total_tabs < self.TOTAL_MAX_TABS:
                # 해당 계정의 컨텍스트에서 새 탭 생성
                try:
                    tab = await context.new_page()
                except Exception as e:
                    logger.warning(f"탭 생성 실패, 브라우저 컨텍스트 재생성 시도 (service_account_id={service_account_id}): {e}")
                    # 브라우저 컨텍스트 재생성
                    await self.handle_browser_closed_error(service_account_id, recreate=True)
                    context = await self.context_manager.get_or_create_context(service_account_id)
                    # 탭 풀 재초기화
                    if service_account_id not in self.tab_pools:
                        self.tab_pools[service_account_id] = {}
                        await self.register_initial_tabs(service_account_id, context)
                    # 재시도
                    tab = await context.new_page()
                    logger.info(f"브라우저 복구 후 탭 생성 성공 (service_account_id={service_account_id})")

                # 자동화 감지 방지 설정
                await tab.set_extra_http_headers({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
                })

                # 고유 탭 ID 생성 (계정 ID 포함)
                tab_id = f"{service_account_id}_{random.randint(1000, 9999)}"
                while tab_id in account_tab_pool or tab_id in self.tab_pool:
                    tab_id = f"{service_account_id}_{random.randint(1000, 9999)}"

                account_tab_pool[tab_id] = tab
                self.tab_pool[tab_id] = tab  # 하위 호환성
                self.tab_last_used[tab_id] = time.time()
                self.tab_in_use[tab_id] = True  # ★ 새 탭도 즉시 잠금
                self.tab_use_count[tab_id] = 0
                self.tab_account[tab_id] = service_account_id
                self.total_active_tabs = total_tabs + 1

                tabs_in_use = sum(1 for in_use in self.tab_in_use.values() if in_use)
                logger.info(f"🔒 새 탭 생성: {tab_id} → 대상 {target_id} (사용 중: {tabs_in_use}/{self.TOTAL_MAX_TABS}, 전체 탭: {total_tabs + 1})")
                break
            else:
                # 모든 탭이 사용 중, 대기
                wait_count += 1
                if wait_count == 1:
                    logger.info(f"대상 {target_id}의 탭 요청 {request_id} 대기 중 (계정 {service_account_id}, 전체 탭: {total_tabs}/{self.TOTAL_MAX_TABS}, 모두 사용 중)")

                # 대기 이벤트 생성
                wait_event = asyncio.Event()
                self.tab_waiters[request_id] = wait_event

                try:
                    await asyncio.wait_for(wait_event.wait(), timeout=self.TAB_WAIT_RETRY_INTERVAL)
                    logger.info(f"대상 {target_id}의 탭 요청 {request_id} 신호 수신")
                    continue
                except asyncio.TimeoutError:
                    self.tab_waiters.pop(request_id, None)
                    await asyncio.sleep(0.5)
                    continue

        # 탭 메타데이터 설정 (tab_in_use는 이미 루프 안에서 True로 설정됨)
        self.tab_current_target[tab_id] = target_id
        self.tab_use_count[tab_id] = self.tab_use_count.get(tab_id, 0) + 1
        self.tab_last_used[tab_id] = time.time()

        # 탭 ID 및 계정 ID 저장 (release_tab에서 사용)
        tab._tab_id = tab_id
        tab._target_id = target_id
        tab._account_id = service_account_id

        logger.debug(f"탭 {tab_id} -> 대상 {target_id} 할당 (계정 {service_account_id}, 사용 횟수: {self.tab_use_count[tab_id]}/{self.MAX_USES_PER_TAB})")
        return tab

    async def release_tab(self, tab: Page):
        """탭 사용을 완료하고 풀로 반환합니다."""
        try:
            if hasattr(tab, '_tab_id'):
                tab_id = tab._tab_id
                target_id = getattr(tab, '_target_id', None)

                if tab_id in self.tab_in_use:
                    # 이미 반환된 탭인지 확인 (중복 반환 방지)
                    if not self.tab_in_use[tab_id]:
                        logger.debug(f"탭 {tab_id} 이미 반환됨 (중복 호출 무시)")
                        return

                    self.tab_in_use[tab_id] = False
                    self.tab_last_used[tab_id] = time.time()
                    self.tab_current_target.pop(tab_id, None)
                    tabs_in_use = sum(1 for in_use in self.tab_in_use.values() if in_use)
                    logger.info(f"🔓 탭 반환: {tab_id} ← 대상 {target_id} (사용 중: {tabs_in_use}/{self.TOTAL_MAX_TABS})")

                    # 대기 중인 요청에 신호 전송
                    if self.tab_waiters:
                        for waiter_id, event in list(self.tab_waiters.items()):
                            event.set()
                            self.tab_waiters.pop(waiter_id, None)
                            logger.debug(f"대기 중인 요청 {waiter_id}에 탭 사용 가능 신호 전송")
                            break  # 한 번에 하나만 깨움
        except Exception as e:
            logger.warning(f"탭 반환 중 오류 발생: {str(e)}")

    async def cleanup_old_tabs(self, force_cleanup: bool = False):
        """오래된 탭을 정리합니다 (계정별 탭 풀 지원)."""
        current_time = time.time()
        tabs_to_remove = []

        # 먼저 탭 풀에 등록되지 않은 고아 탭들 정리
        await self._cleanup_orphan_tabs()

        if not self.tab_last_used:
            return 0

        # 사용 중이 아닌 탭만 정리 대상
        for tab_id, last_used in list(self.tab_last_used.items()):
            if self.tab_in_use.get(tab_id, False):
                continue

            # 사용 횟수 초과 탭 우선 정리
            if self.tab_use_count.get(tab_id, 0) >= self.MAX_USES_PER_TAB:
                tabs_to_remove.append(tab_id)
                logger.info(f"탭 {tab_id} 사용 횟수 초과로 정리 대상 ({self.tab_use_count.get(tab_id, 0)}/{self.MAX_USES_PER_TAB})")
                continue

            # 임계값 초과 탭 정리
            if current_time - last_used > settings.TAB_CLEANUP_THRESHOLD:
                tabs_to_remove.append(tab_id)

        total_tabs = sum(len(pool) for pool in self.tab_pools.values())
        if tabs_to_remove:
            logger.info(f"탭 풀 정리: {len(tabs_to_remove)}개 정리 대상 (현재 탭 수: {total_tabs})")

        # 제거 대상 탭 정리
        for tab_id in tabs_to_remove:
            service_account_id = self.tab_account.get(tab_id)
            if service_account_id is not None and service_account_id in self.tab_pools:
                if tab_id in self.tab_pools[service_account_id]:
                    try:
                        logger.debug(f"탭 {tab_id} 정리 시작 (계정 {service_account_id})")
                        await self.tab_pools[service_account_id][tab_id].close()
                        del self.tab_pools[service_account_id][tab_id]
                    except Exception as e:
                        logger.warning(f"탭 정리 중 오류 발생: {str(e)}")

            # 하위 호환성을 위한 전역 탭 풀에서도 제거
            if tab_id in self.tab_pool:
                try:
                    if service_account_id is None:
                        await self.tab_pool[tab_id].close()
                    del self.tab_pool[tab_id]
                except Exception as e:
                    logger.warning(f"탭 정리 중 오류 발생: {str(e)}")

            # 메타데이터 정리
            self.tab_last_used.pop(tab_id, None)
            self.tab_in_use.pop(tab_id, None)
            self.tab_use_count.pop(tab_id, None)
            self.tab_current_target.pop(tab_id, None)
            self.tab_account.pop(tab_id, None)
            logger.debug(f"탭 {tab_id} 정리 완료")

        # 전체 활성 탭 수 업데이트
        self.total_active_tabs = sum(len(pool) for pool in self.tab_pools.values())

        if tabs_to_remove:
            logger.info(f"탭 풀 정리 완료: {len(tabs_to_remove)}개 제거, 남은 탭 수: {self.total_active_tabs}")

        return len(tabs_to_remove)

    async def _cleanup_orphan_tabs(self):
        """
        탭 풀에 등록되지 않은 고아 탭들을 정리합니다.

        브라우저 컨텍스트에 존재하지만 탭 풀에서 관리되지 않는 탭들을 찾아서 닫습니다.
        특히 about:blank 상태로 방치된 탭들을 정리합니다.
        """
        orphan_count = 0
        try:
            # 모든 브라우저 컨텍스트의 페이지 확인
            for service_account_id, context in list(self.context_manager.browser_contexts.items()):
                try:
                    pages = context.pages
                except Exception:
                    # 컨텍스트가 닫혀있으면 건너뜀
                    continue

                # 탭 풀에 등록된 페이지 목록
                registered_pages = set()
                if service_account_id in self.tab_pools:
                    registered_pages = set(self.tab_pools[service_account_id].values())

                # 컨텍스트의 모든 페이지 확인
                for page in pages:
                    # 이미 탭 풀에 등록된 페이지는 건너뜀
                    if page in registered_pages:
                        continue

                    # _tab_id가 있으면 탭 풀에서 관리되는 것
                    if hasattr(page, '_tab_id') and page._tab_id in self.tab_pool:
                        continue

                    # 탭 풀에 등록되지 않은 페이지 (고아 탭)
                    try:
                        page_url = page.url
                        # about:blank나 빈 페이지는 닫기
                        # 또는 최대 탭 수를 초과한 경우에도 닫기
                        total_tabs = sum(len(pool) for pool in self.tab_pools.values())
                        if page_url == "about:blank" or total_tabs > self.TOTAL_MAX_TABS:
                            await page.close()
                            orphan_count += 1
                            logger.info(f"고아 탭 정리: service_account_id={service_account_id}, url={page_url}")
                    except Exception as e:
                        logger.debug(f"고아 탭 정리 중 오류 (무시): {e}")

            if orphan_count > 0:
                logger.info(f"고아 탭 {orphan_count}개 정리 완료")

        except Exception as e:
            logger.warning(f"고아 탭 정리 중 오류: {e}")

        return orphan_count

    async def periodic_cleanup(self) -> int:
        """주기적 고아/오래된 탭 정리를 단일 cleanup 경로로 실행한다."""
        return await self.cleanup_old_tabs()

    async def _is_tab_closed(self, tab: Page) -> bool:
        """탭이 닫혔는지 확인합니다."""
        try:
            if tab.is_closed():
                return True
            await tab.evaluate("() => true")
            return False
        except Exception:
            return True

    async def _remove_tab_from_pool(self, tab_id: str, service_account_id: int):
        """탭 풀에서 탭을 제거합니다."""
        try:
            # 계정별 탭 풀에서 제거
            if service_account_id in self.tab_pools and tab_id in self.tab_pools[service_account_id]:
                del self.tab_pools[service_account_id][tab_id]

            # 하위 호환성 탭 풀에서 제거
            self.tab_pool.pop(tab_id, None)

            # 탭 관련 상태 정리
            self.tab_last_used.pop(tab_id, None)
            self.tab_in_use.pop(tab_id, None)
            self.tab_use_count.pop(tab_id, None)
            self.tab_current_target.pop(tab_id, None)
            self.tab_account.pop(tab_id, None)

            # 전체 탭 수 업데이트
            self.total_active_tabs = sum(len(pool) for pool in self.tab_pools.values())
            logger.info(f"탭 {tab_id} 풀에서 제거됨 (전체 탭: {self.total_active_tabs}/{self.TOTAL_MAX_TABS})")
        except Exception as e:
            logger.error(f"탭 풀 제거 중 오류: {str(e)}")

    async def register_initial_tabs(self, service_account_id: int, context: BrowserContext) -> int:
        """
        브라우저 컨텍스트의 기존 페이지들을 탭 풀에 등록합니다.
        launch_persistent_context로 생성된 초기 빈 탭을 재사용하기 위함.

        Args:
            service_account_id: 계정 ID
            context: 브라우저 컨텍스트

        Returns:
            int: 등록된 탭 수
        """
        pages = context.pages
        registered_count = 0

        # 계정별 탭 풀 초기화
        if service_account_id not in self.tab_pools:
            self.tab_pools[service_account_id] = {}

        for page in pages:
            # 이미 등록된 탭인지 확인
            if hasattr(page, '_tab_id') and page._tab_id in self.tab_pool:
                continue

            # URL이 about:blank인 경우만 등록 (초기 빈 탭)
            if page.url == "about:blank":
                # 고유 탭 ID 생성
                tab_id = f"{service_account_id}_{random.randint(1000, 9999)}"
                while tab_id in self.tab_pools[service_account_id] or tab_id in self.tab_pool:
                    tab_id = f"{service_account_id}_{random.randint(1000, 9999)}"

                # 풀에 등록
                self.tab_pools[service_account_id][tab_id] = page
                self.tab_pool[tab_id] = page  # 하위 호환성
                self.tab_last_used[tab_id] = time.time()
                self.tab_in_use[tab_id] = False
                self.tab_use_count[tab_id] = 0
                self.tab_account[tab_id] = service_account_id

                # 탭에 메타데이터 저장
                page._tab_id = tab_id
                page._account_id = service_account_id

                registered_count += 1
                logger.info(f"초기 빈 탭 등록: {tab_id} (service_account_id={service_account_id})")

        # 전체 활성 탭 수 업데이트
        self.total_active_tabs = sum(len(pool) for pool in self.tab_pools.values())

        if registered_count > 0:
            logger.info(f"계정 {service_account_id}의 초기 탭 {registered_count}개 등록 완료 (전체 탭: {self.total_active_tabs}/{self.TOTAL_MAX_TABS})")

        return registered_count

    async def handle_browser_closed_error(self, service_account_id: int, recreate: bool = False) -> bool:
        """브라우저가 닫혔을 때 해당 계정의 컨텍스트와 탭을 정리합니다.

        Args:
            service_account_id: 계정 ID
            recreate: True면 정리 후 즉시 재생성까지 수행

        Returns:
            bool: True if cleanup was performed, False if recovery already in progress
        """
        # 이미 복구 진행 중이면 스킵 (race condition 방지)
        if self._recovery_in_progress.get(service_account_id, False):
            logger.info(f"계정 {service_account_id}의 브라우저 복구가 이미 진행 중입니다. 정리 스킵.")
            return False

        # context_manager의 Lock 획득 (브라우저 생성과 동기화)
        context_lock = await self.context_manager._get_context_lock(service_account_id)

        async with context_lock:
            # Lock 획득 후 다시 확인 (다른 태스크가 이미 처리했을 수 있음)
            if self._recovery_in_progress.get(service_account_id, False):
                logger.info(f"계정 {service_account_id}의 브라우저 복구가 이미 진행 중입니다. 정리 스킵.")
                return False

            # 복구 진행 중 플래그 설정
            self._recovery_in_progress[service_account_id] = True

            try:
                logger.warning(f"계정 {service_account_id}의 브라우저가 닫혔습니다. 컨텍스트 및 탭 정리 중...")

                # 해당 계정의 모든 탭 제거
                if service_account_id in self.tab_pools:
                    for tab_id in list(self.tab_pools[service_account_id].keys()):
                        await self._remove_tab_from_pool(tab_id, service_account_id)
                    try:
                        del self.tab_pools[service_account_id]
                    except KeyError:
                        pass

                # 브라우저 컨텍스트 제거
                if service_account_id in self.context_manager.browser_contexts:
                    try:
                        del self.context_manager.browser_contexts[service_account_id]
                    except KeyError:
                        pass

                logger.info(f"계정 {service_account_id}의 브라우저 정리 완료.")

                # recreate=True면 즉시 재생성 (Lock 내에서 수행하여 race condition 방지)
                if recreate:
                    logger.info(f"계정 {service_account_id}의 브라우저 재생성 시작...")
                    try:
                        # _create_browser_context 직접 호출 (Lock은 이미 획득됨)
                        context = await self.context_manager._create_browser_context(service_account_id)
                        self.context_manager.browser_contexts[service_account_id] = context
                        logger.info(f"계정 {service_account_id}의 브라우저 재생성 완료")
                    except Exception as e:
                        logger.error(f"계정 {service_account_id}의 브라우저 재생성 실패: {e}")
                        raise

                return True
            finally:
                # 복구 진행 중 플래그 해제
                self._recovery_in_progress[service_account_id] = False

    async def close_all_tabs(self) -> int:
        """
        모든 탭을 강제로 닫습니다.

        스나이핑 시작 전 모니터링 탭을 정리할 때 사용합니다.
        브라우저 컨텍스트는 유지하고 탭만 닫습니다.

        Returns:
            닫힌 탭 수
        """
        closed_count = 0

        # 모든 계정의 탭 풀 정리
        for service_account_id in list(self.tab_pools.keys()):
            tab_pool = self.tab_pools[service_account_id]

            for tab_id in list(tab_pool.keys()):
                try:
                    tab = tab_pool[tab_id]

                    # 사용 중 상태 해제
                    self.tab_in_use[tab_id] = False

                    # 탭 닫기
                    try:
                        if not tab.is_closed():
                            await tab.close()
                    except Exception as e:
                        logger.debug(f"탭 닫기 오류 (무시): {e}")

                    # 풀에서 제거
                    del tab_pool[tab_id]

                    # 메타데이터 정리
                    self.tab_pool.pop(tab_id, None)
                    self.tab_last_used.pop(tab_id, None)
                    self.tab_in_use.pop(tab_id, None)
                    self.tab_use_count.pop(tab_id, None)
                    self.tab_current_target.pop(tab_id, None)
                    self.tab_account.pop(tab_id, None)

                    closed_count += 1
                    logger.debug(f"탭 {tab_id} 닫힘 (service_account_id={service_account_id})")

                except Exception as e:
                    logger.warning(f"탭 {tab_id} 정리 중 오류: {e}")

        # 전체 활성 탭 수 업데이트
        self.total_active_tabs = 0

        # 대기 중인 요청들에게 신호 전송 (탭이 해제됨)
        for waiter_id, event in list(self.tab_waiters.items()):
            event.set()
            self.tab_waiters.pop(waiter_id, None)

        logger.info(f"[TAB-POOL] 모든 탭 닫기 완료: {closed_count}개 탭 정리됨")
        return closed_count

    def get_pool_size(self, service_account_id: Optional[int] = None) -> int:
        """
        탭 풀의 현재 크기를 반환합니다.

        Args:
            service_account_id: 특정 계정의 탭 풀 크기만 반환 (None이면 전체)

        Returns:
            탭 풀 크기
        """
        if service_account_id is not None:
            return len(self.tab_pools.get(service_account_id, {}))
        return sum(len(pool) for pool in self.tab_pools.values())

    async def warmup(self, min_tabs: int = 3, service_account_id: Optional[int] = None):
        """
        탭 풀을 미리 워밍업합니다.
        브라우저 컨텍스트와 탭을 미리 생성하여 스나이핑 시 지연을 방지합니다.

        Args:
            min_tabs: 최소 탭 수 (기본 3개)
            service_account_id: 계정 ID (None이면 기본 계정)
        """
        target_account_id = service_account_id or 1

        try:
            # 1. 브라우저 컨텍스트 확보
            context = await self.context_manager.get_or_create_context(target_account_id)
            if not context:
                logger.warning(f"[TAB-WARMUP] 브라우저 컨텍스트 생성 실패 (service_account_id={target_account_id})")
                return

            # 2. 현재 풀 크기 확인
            current_size = len(self.tab_pools.get(target_account_id, {}))

            # 3. 필요한 탭 수 계산
            tabs_needed = max(0, min_tabs - current_size)
            if tabs_needed == 0:
                logger.info(f"[TAB-WARMUP] 탭 풀 충분함 (service_account_id={target_account_id}, 크기={current_size})")
                return

            # 4. 탭 풀 초기화 (필요한 경우)
            if target_account_id not in self.tab_pools:
                self.tab_pools[target_account_id] = {}
                # 기존 빈 탭 등록
                await self.register_initial_tabs(target_account_id, context)
                current_size = len(self.tab_pools.get(target_account_id, {}))
                tabs_needed = max(0, min_tabs - current_size)

            # 5. 부족한 탭 생성
            logger.info(f"[TAB-WARMUP] 탭 {tabs_needed}개 생성 중 (service_account_id={target_account_id})")

            for i in range(tabs_needed):
                try:
                    # 전체 탭 수 확인
                    total_tabs = sum(len(pool) for pool in self.tab_pools.values())
                    if total_tabs >= self.TOTAL_MAX_TABS:
                        logger.warning(f"[TAB-WARMUP] 최대 탭 수 도달 ({total_tabs}/{self.TOTAL_MAX_TABS})")
                        break

                    # 새 탭 생성
                    page = await context.new_page()

                    # 자동화 감지 방지 설정
                    await page.set_extra_http_headers({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
                    })

                    # 고유 탭 ID 생성
                    tab_id = f"{target_account_id}_{random.randint(1000, 9999)}"
                    while tab_id in self.tab_pools[target_account_id] or tab_id in self.tab_pool:
                        tab_id = f"{target_account_id}_{random.randint(1000, 9999)}"

                    # 풀에 등록
                    self.tab_pools[target_account_id][tab_id] = page
                    self.tab_pool[tab_id] = page
                    self.tab_last_used[tab_id] = time.time()
                    self.tab_in_use[tab_id] = False
                    self.tab_use_count[tab_id] = 0
                    self.tab_account[tab_id] = target_account_id

                    # 탭에 메타데이터 저장
                    page._tab_id = tab_id
                    page._account_id = target_account_id

                    logger.debug(f"[TAB-WARMUP] 탭 생성: {tab_id}")

                except Exception as e:
                    logger.error(f"[TAB-WARMUP] 탭 생성 실패: {e}")
                    break

            # 6. 결과 업데이트
            self.total_active_tabs = sum(len(pool) for pool in self.tab_pools.values())
            final_size = len(self.tab_pools.get(target_account_id, {}))
            logger.info(f"[TAB-WARMUP] 워밍업 완료 (service_account_id={target_account_id}, 탭 수: {current_size} → {final_size})")

        except Exception as e:
            logger.error(f"[TAB-WARMUP] 워밍업 중 오류: {e}")

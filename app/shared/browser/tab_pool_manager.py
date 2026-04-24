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
        self.TAB_REQUEST_TIMEOUT = settings.TAB_REQUEST_TIMEOUT  # inner polling gate (BrowserManager outer ≈ +5s)
        self.TAB_WAIT_RETRY_INTERVAL = settings.TAB_WAIT_RETRY_INTERVAL
        self.TOTAL_MAX_TABS = settings.TOTAL_MAX_TABS  # 시간 분할 재사용 전제 — 풀 크기 확대로 우회 금지
        self.MAX_USES_PER_TAB = settings.MAX_USES_PER_TAB

        # H2: context.new_page() hang 차단 타임아웃 (30s — outer BrowserManager gate 60s의 절반)
        self.NEW_PAGE_TIMEOUT = 30.0

        # 전체 현재 활성 탭 수 추적
        self.total_active_tabs = 0

        # 계정별 브라우저 복구 진행 중 플래그 (race condition 방지)
        self._recovery_in_progress: Dict[int, bool] = {}

    def _count_budgeted_pages(self, context: BrowserContext) -> int:
        """visible sentinel(visible_*) 탭을 제외한 예산 소비 탭 수를 반환한다.

        pool 탭과 orphan 탭은 그대로 카운트해 혼합 포화(pool+orphan)를 가리지 않는다.
        secondary gate(`get_tab()`)의 starvation 판단 전용 — cleanup overflow 조건에는 사용하지 않는다.
        """
        count = 0
        for p in context.pages:
            if p.is_closed():
                continue
            tab_id = getattr(p, '_tab_id', None)
            if isinstance(tab_id, str) and tab_id.startswith('visible_'):
                continue
            count += 1
        return count

    def _is_stale_login_check(self, page: Page) -> bool:
        """login_check 마커가 있고 30초 이상 경과한 탭이면 True 반환.

        형식: login_check_{type}_{sid}_{unix_ts}
        파싱 실패 또는 prefix 불일치 시 False(안전 기본값).
        """
        tab_id = getattr(page, '_tab_id', None)
        if not isinstance(tab_id, str):
            return False
        if not tab_id.startswith('login_check_'):
            return False
        parts = tab_id.split('_')
        # login_check_{type}_{sid}_{ts} → 최소 4개 세그먼트
        if len(parts) < 4:
            return False
        try:
            ts = int(parts[-1])
            return time.time() - ts > 30
        except (ValueError, IndexError):
            return False

    async def get_tab(
        self,
        target_id: int,
        service_account_id: Optional[int] = None,
        inner_timeout: Optional[float] = None,
    ) -> Page:
        """계정별 탭 풀에서 사용 가능한 탭을 가져오거나 새로 생성합니다.

        Args:
            target_id: 모니터링 대상 (스케줄) ID
            service_account_id: 계정 ID (None이면 기본 계정 사용)
            inner_timeout: 내부 폴링 타임아웃 (초). BrowserManager가 outer-5s로 계산해 전달.
                None이면 TAB_REQUEST_TIMEOUT 사용. H5 inner/outer budget 분리를 위한 파라미터.

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
        # H5: inner_timeout으로 BrowserManager outer gate보다 5초 먼저 TimeoutError surface
        max_wait_time = inner_timeout if inner_timeout is not None else self.TAB_REQUEST_TIMEOUT

        # Phase 1 진입 로그: pool snapshot으로 starvation 진단 가능
        _entry_status = self.get_status()
        _entry_budgeted = self._count_budgeted_pages(context)
        logger.info(
            f"[TAB-POOL] get_tab 진입: target={target_id}, account={service_account_id}, "
            f"total={_entry_status['total_active_tabs']}/{self.TOTAL_MAX_TABS}, "
            f"budgeted={_entry_budgeted}/{self.TOTAL_MAX_TABS}, "
            f"in_use={_entry_status['in_use_count']}, waiters={_entry_status['waiter_count']}, "
            f"inner_timeout={max_wait_time:.0f}s"
        )

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
                # secondary gate: visible sentinel(visible_*) 제외 예산 탭 수 체크
                # visible sentinel은 사용자 가시 창이므로 워커 예산에서 제외
                # pool 탭/orphan은 계속 카운트해 혼합 포화를 가리지 않음
                actual_pages = self._count_budgeted_pages(context)
                if actual_pages >= self.TOTAL_MAX_TABS:
                    await self._cleanup_orphan_tabs()
                    actual_pages = self._count_budgeted_pages(context)
                    if actual_pages >= self.TOTAL_MAX_TABS:
                        logger.warning(
                            f"[TAB-POOL] 실제 탭 초과({actual_pages}/{self.TOTAL_MAX_TABS}), 재시도 대기 "
                            f"(service_account_id={service_account_id})"
                        )
                        await asyncio.sleep(self.TAB_WAIT_RETRY_INTERVAL)
                        continue

                # Phase 1: 새 탭 생성 직전 snapshot — new_page hang 원인 진단
                _pre_create_status = self.get_status()
                _pre_create_budgeted = self._count_budgeted_pages(context)
                logger.info(
                    f"[TAB-POOL] new_page 생성 결정: account={service_account_id}, "
                    f"pool_total={_pre_create_status['total_active_tabs']}, "
                    f"budgeted={_pre_create_budgeted}/{self.TOTAL_MAX_TABS}, "
                    f"in_use={_pre_create_status['in_use_count']}, "
                    f"waiters={_pre_create_status['waiter_count']}, "
                    f"account_pools={_pre_create_status['account_pool_sizes']}"
                )

                # new_page()~풀 등록 사이에서 CancelledError가 와도 미등록 탭이 남지 않도록 보호
                new_tab = None
                try:
                    context, new_tab = await self._create_page_with_timeout(context, service_account_id)
                    # helper 반환 직후 stale 참조 재바인딩 (recreate 시 self.tab_pools[id]가 교체됨)
                    account_tab_pool = self.tab_pools[service_account_id]
                    total_tabs = sum(len(pool) for pool in self.tab_pools.values())

                    # 자동화 감지 방지 설정
                    await new_tab.set_extra_http_headers({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
                    })

                    # 고유 탭 ID 생성 (계정 ID 포함)
                    tab_id = f"{service_account_id}_{random.randint(1000, 9999)}"
                    while tab_id in account_tab_pool or tab_id in self.tab_pool:
                        tab_id = f"{service_account_id}_{random.randint(1000, 9999)}"

                    account_tab_pool[tab_id] = new_tab
                    self.tab_pool[tab_id] = new_tab  # 하위 호환성
                    self.tab_last_used[tab_id] = time.time()
                    self.tab_in_use[tab_id] = True  # ★ 새 탭도 즉시 잠금
                    self.tab_use_count[tab_id] = 0
                    self.tab_account[tab_id] = service_account_id
                    self.total_active_tabs = total_tabs + 1

                    tab = new_tab
                    new_tab = None  # 등록 성공 → finally의 close 방지

                    tabs_in_use = sum(1 for in_use in self.tab_in_use.values() if in_use)
                    logger.info(f"🔒 새 탭 생성: {tab_id} → 대상 {target_id} (사용 중: {tabs_in_use}/{self.TOTAL_MAX_TABS}, 전체 탭: {total_tabs + 1})")
                    break

                finally:
                    # 등록 전 cancel/error로 new_tab이 아직 None이 아니면 미등록 탭 정리
                    if new_tab is not None:
                        try:
                            await asyncio.shield(new_tab.close())
                            logger.warning(f"[TAB-POOL] 미등록 탭 정리: cancel/error 발생 (service_account_id={service_account_id})")
                        except Exception as close_err:
                            logger.debug(f"[TAB-POOL] 미등록 탭 close 실패 (무시): {close_err}")
            else:
                # 모든 탭이 사용 중, 대기
                wait_count += 1
                if wait_count == 1:
                    # Phase 1: 첫 wait-loop 진입 시 full snapshot — starvation 진단
                    _wait_status = self.get_status()
                    logger.info(
                        f"[TAB-POOL] 대기 시작: target={target_id}, account={service_account_id}, "
                        f"waiter_count={_wait_status['waiter_count']}, "
                        f"dead={_wait_status['dead_waiter_count']}, "
                        f"total_tabs={_wait_status['total_active_tabs']}/{self.TOTAL_MAX_TABS}, "
                        f"in_use={_wait_status['in_use_count']}, "
                        f"elapsed={time.time() - start_time:.1f}s"
                    )

                # 대기 이벤트 생성 — try/finally로 CancelledError 포함 모든 종료 경로에서 정리
                wait_event = asyncio.Event()
                self.tab_waiters[request_id] = wait_event
                try:
                    await asyncio.wait_for(wait_event.wait(), timeout=self.TAB_WAIT_RETRY_INTERVAL)
                    logger.info(f"대상 {target_id}의 탭 요청 {request_id} 신호 수신")
                    continue
                except asyncio.TimeoutError:
                    await asyncio.sleep(0.5)
                    continue
                finally:
                    # release_tab이 이미 pop했으면 no-op; CancelledError 시에도 dead waiter 방지
                    self.tab_waiters.pop(request_id, None)

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
        """탭 사용을 완료하고 풀로 반환합니다.

        H1 수정: tab_in_use=False는 finally로 보장 — _wake_waiters 예외와 무관하게 해제.
        _wake_waiters는 별도 try/except로 분리해 실패해도 재사용 경로를 막지 않는다.
        """
        # tab_id를 최상단에서 추출 — _tab_id 없거나 pending marker면 DEBUG no-op
        tab_id = getattr(tab, '_tab_id', None)
        if tab_id is None:
            logger.debug("[TAB-POOL] release_tab: _tab_id 없음, 무시")
            return
        if tab_id == "__pending__":
            logger.debug("[TAB-POOL] release_tab: pending 마커 탭 무시 (등록 전 cancel 경로)")
            return

        target_id = getattr(tab, '_target_id', None)

        if tab_id not in self.tab_in_use:
            logger.debug(f"[TAB-POOL] release_tab: {tab_id} tab_in_use에 없음, 무시")
            return

        # 이미 반환된 탭 중복 체크
        if not self.tab_in_use[tab_id]:
            logger.debug(f"탭 {tab_id} 이미 반환됨 (중복 호출 무시)")
            return

        # in_use=False는 finally에서 보장 — 예외와 무관하게 반드시 해제
        try:
            try:
                self.tab_last_used[tab_id] = time.time()
                self.tab_current_target.pop(tab_id, None)
                tabs_in_use = sum(1 for in_use in self.tab_in_use.values() if in_use)
                logger.info(f"🔓 탭 반환: {tab_id} ← 대상 {target_id} (사용 중: {tabs_in_use}/{self.TOTAL_MAX_TABS})")
            finally:
                self.tab_in_use[tab_id] = False  # 예외와 무관하게 보장
        except Exception as e:
            logger.warning(f"[TAB-POOL] release error tab_id={tab_id}: {str(e)}")

        # _wake_waiters는 in_use 해제 이후 별도 try — 실패해도 in_use=False는 이미 완료
        if self.tab_waiters:
            try:
                woken, dead_cleaned = self._wake_waiters(strategy="one")
                if dead_cleaned > 0:
                    logger.info(
                        f"[TAB-POOL] dead waiter {dead_cleaned}건 정리, "
                        f"live {woken}건 깨움, 잔여 {len(self.tab_waiters)}건"
                    )
                elif woken > 0:
                    logger.debug(f"[TAB-POOL] waiter 깨움, 잔여 {len(self.tab_waiters)}건")
            except Exception as e:
                status = self.get_status()
                logger.warning(
                    f"[TAB-POOL] release error _wake_waiters tab_id={tab_id}: {e}, "
                    f"status={status}"
                )

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
        skipped_pool = 0
        skipped_sentinel = 0
        skipped_login_check = 0
        skipped_other = 0
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
                        skipped_pool += 1
                        logger.debug(
                            f"[TAB-POOL] cleanup skip: reason=pool, "
                            f"url={getattr(page, 'url', '?')}, "
                            f"tab_id={getattr(page, '_tab_id', None)}, sid={service_account_id}"
                        )
                        continue

                    # _tab_id가 있으면 풀 관리 탭이거나 visible sentinel 탭 — 정리 대상 아님
                    if hasattr(page, '_tab_id'):
                        tab_id = page._tab_id
                        # pool 등록 탭 또는 visible sentinel(사용자 가시 창) — session_manager가 수명 관리
                        if tab_id in self.tab_pool or (isinstance(tab_id, str) and tab_id.startswith('visible_')):
                            reason = "sentinel" if isinstance(tab_id, str) and tab_id.startswith('visible_') else "pool"
                            if reason == "sentinel":
                                skipped_sentinel += 1
                            else:
                                skipped_pool += 1
                            logger.debug(
                                f"[TAB-POOL] cleanup skip: reason={reason}, "
                                f"url={getattr(page, 'url', '?')}, "
                                f"tab_id={tab_id}, sid={service_account_id}"
                            )
                            continue

                        # login_check 마커: stale이면 정리, 근래 생성이면 보존
                        if isinstance(tab_id, str) and tab_id.startswith('login_check_'):
                            if self._is_stale_login_check(page):
                                try:
                                    await page.close()
                                    orphan_count += 1
                                    logger.info(
                                        f"[TAB-POOL] stale login_check closed: "
                                        f"sid={service_account_id}, tab_id={tab_id}"
                                    )
                                except Exception as e:
                                    logger.debug(f"[TAB-POOL] login_check close 실패 (무시): {e}")
                            else:
                                skipped_login_check += 1
                                logger.debug(
                                    f"[TAB-POOL] cleanup skip: reason=login_check_recent, "
                                    f"url={getattr(page, 'url', '?')}, "
                                    f"tab_id={tab_id}, sid={service_account_id}"
                                )
                            continue

                    # 탭 풀에 등록되지 않은 페이지 (고아 탭)
                    try:
                        page_url = page.url
                        actual_pages_before = len([p for p in context.pages if not p.is_closed()])
                        if (page_url == "about:blank"
                                or page_url.startswith("chrome-error://")
                                or actual_pages_before >= self.TOTAL_MAX_TABS):
                            await page.close()
                            orphan_count += 1
                            actual_pages_after = len([p for p in context.pages if not p.is_closed()])
                            logger.info(
                                f"[TAB-POOL] exact-limit orphan cleaned: "
                                f"sid={service_account_id}, url={page_url}, "
                                f"actual_before={actual_pages_before}, actual_after={actual_pages_after}, "
                                f"registered={len(registered_pages)}"
                            )
                            logger.info(f"고아 탭 정리: service_account_id={service_account_id}, url={page_url}")
                        else:
                            skipped_other += 1
                            logger.debug(
                                f"[TAB-POOL] cleanup skip: reason=other, "
                                f"url={page_url}, tab_id={getattr(page, '_tab_id', None)}, "
                                f"sid={service_account_id}"
                            )
                    except Exception as e:
                        logger.debug(f"고아 탭 정리 중 오류 (무시): {e}")

            if orphan_count > 0:
                logger.info(f"고아 탭 {orphan_count}개 정리 완료")

        except Exception as e:
            logger.warning(f"고아 탭 정리 중 오류: {e}")

        # cleanup 호출마다 summary 출력 — skip=0이어도 재발 진단에 필요
        logger.info(
            f"[TAB-POOL] cleanup summary: closed={orphan_count}, "
            f"skipped_pool={skipped_pool}, skipped_sentinel={skipped_sentinel}, "
            f"skipped_login_check={skipped_login_check}, skipped_other={skipped_other}"
        )

        return orphan_count

    async def periodic_cleanup(self) -> int:
        """주기적 고아 탭 정리 — cleanup_old_tabs 단일 경유로 중복 없이 실행.

        Returns:
            int: 닫힌 탭 수
        """
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

    async def _create_page_with_timeout(
        self,
        context: BrowserContext,
        service_account_id: int,
    ) -> tuple[BrowserContext, Page]:
        """context.new_page()를 NEW_PAGE_TIMEOUT으로 감싸고, hang/recoverable error 시
        handle_browser_closed_error + get_or_create_context를 거쳐 fresh context로 재시도한다.

        반환 전 page._tab_id = "__pending__"을 즉시 설정한다 (popup guard 계약 유지).
        """
        try:
            page = await asyncio.wait_for(
                context.new_page(),
                timeout=self.NEW_PAGE_TIMEOUT,
            )
            page._tab_id = "__pending__"
            return context, page
        except asyncio.TimeoutError:
            logger.warning(
                f"[TAB-POOL] new_page hang 감지 ({self.NEW_PAGE_TIMEOUT:.0f}s), "
                f"recreate 시도 (service_account_id={service_account_id})"
            )
        except Exception as e:
            logger.warning(
                f"탭 생성 실패, 브라우저 컨텍스트 재생성 시도 (service_account_id={service_account_id}): {e}"
            )

        await self.handle_browser_closed_error(service_account_id, recreate=True)
        context = await self.context_manager.get_or_create_context(service_account_id)
        if service_account_id not in self.tab_pools:
            self.tab_pools[service_account_id] = {}
            await self.register_initial_tabs(service_account_id, context)
        page = await asyncio.wait_for(
            context.new_page(),
            timeout=self.NEW_PAGE_TIMEOUT,
        )
        page._tab_id = "__pending__"
        logger.info(f"브라우저 복구 후 탭 생성 성공 (service_account_id={service_account_id})")
        return context, page

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

        # 대기 중인 요청들에게 신호 전송 (탭이 해제됨, dead waiter 함께 정리)
        woken, dead_cleaned = self._wake_waiters(strategy="all")
        if dead_cleaned > 0:
            logger.info(f"[TAB-POOL] close_all_tabs: dead waiter {dead_cleaned}건 정리")

        logger.info(f"[TAB-POOL] 모든 탭 닫기 완료: {closed_count}개 탭 정리됨")
        return closed_count

    def _wake_waiters(self, strategy: str = "one") -> tuple:
        """dead waiter를 건너뛰고 live waiter에게 탭 가용 신호를 전송한다.

        strategy="one": live waiter 1건만 깨움 (release_tab용)
        strategy="all": 모든 live waiter 깨움 (close_all_tabs용)

        Returns:
            (woken_count, dead_cleaned_count)
        """
        woken = 0
        dead_cleaned = 0
        for waiter_id, event in list(self.tab_waiters.items()):
            if event.is_set():
                # 이미 set된 waiter는 dead (cancel된 코루틴의 잔재)
                self.tab_waiters.pop(waiter_id, None)
                dead_cleaned += 1
                continue
            event.set()
            self.tab_waiters.pop(waiter_id, None)
            woken += 1
            if strategy == "one":
                break
        return woken, dead_cleaned

    def get_status(self) -> dict:
        """탭 풀 상태 진단 정보 반환.

        Returns:
            dict: total_active_tabs, budgeted_pages, in_use_count, waiter_count, dead_waiter_count, account_pool_sizes
        """
        total_active = sum(len(pool) for pool in self.tab_pools.values())
        in_use_count = sum(1 for v in self.tab_in_use.values() if v)
        dead_waiter_count = sum(1 for e in self.tab_waiters.values() if e.is_set())
        account_pool_sizes = {
            account_id: len(pool)
            for account_id, pool in self.tab_pools.items()
        }
        # budgeted_pages: account별 visible sentinel 제외 예산 탭 수
        budgeted_pages = {}
        for account_id, ctx in list(self.context_manager.browser_contexts.items()):
            try:
                budgeted_pages[account_id] = self._count_budgeted_pages(ctx)
            except Exception:
                pass
        return {
            "total_active_tabs": total_active,
            "budgeted_pages": budgeted_pages,
            "in_use_count": in_use_count,
            "waiter_count": len(self.tab_waiters),
            "dead_waiter_count": dead_waiter_count,
            "account_pool_sizes": account_pool_sizes,
        }

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

                    # 새 탭 생성 (helper로 hang/recreate 계약 공유)
                    context, page = await self._create_page_with_timeout(context, target_account_id)

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

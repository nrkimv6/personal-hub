"""
Google 검색 큐 처리 워커.

API 서버에서 추가된 검색 요청을 큐에서 가져와 처리합니다.
Session 0 (NSSM 서비스)에서는 브라우저 사용이 불가하므로
사용자 세션의 워커에서 처리합니다.

실행 방법:
    WorkerOrchestrator에서 등록하여 실행
    (app/worker/main.py 참조)

주요 기능:
    - google_search_queue 테이블에서 pending 요청 조회
    - GoogleSearchCrawler를 사용하여 검색 수행
    - 결과를 google_search_history, google_search_results에 저장
    - saved_search 연결 시 마지막 실행 정보 업데이트

Redis 큐 지원:
    - Redis 연결 시: Redis 큐에서 작업 수신
    - Redis 미연결 시: SQLite 폴링 fallback
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from app.core.database import db_circuit
from app.services.failure_alert_delivery import report_failure_alert
from app.services.failure_alert_policy import FailureEvent
from app.shared.worker.base_worker import BaseWorker
from app.shared.worker.exceptions import is_browser_closed_error
from app.database import SessionLocal
from app.models.google_search import (
    GoogleSearchQueue,
    GoogleSearchHistory,
    GoogleSearchResult,
    GoogleSavedSearch,
)
from app.modules.google_search.services.crawler import (
    GoogleSearchCrawler,
    CrawlOptions,
    CaptchaDetectedError,
)
from app.modules.google_search.services.queue_service import recover_pending_google_searches
from app.shared.browser.browser_manager import BrowserManager
from app.shared.redis import RedisClient, RedisQueue
from app.shared.redis.queue import GOOGLE_SEARCH_QUEUE

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

# 페이지당 budget: goto(domcontentloaded ~10s) + sleep(1.5s) + wait_for_selector(10s)
_PER_PAGE_BUDGET_SECONDS = 25.0
# 페이지 사이 delay budget 배수 (max_delay 기준)
_INTER_PAGE_DELAY_FACTOR = 1.0


def _compute_search_operation_timeout(options: CrawlOptions) -> float:
    """Google 검색 콜백 타임아웃 계산.

    페이지당 25초(goto + sleep + selector) + 페이지 사이 max_delay를 기준으로
    전체 예상 소요 시간을 산출한다.
    DEFAULT_OPERATION_TIMEOUT(60s)를 하한으로 사용해 단일 페이지에서 과도하게 늘리지 않는다.
    """
    n = max(1, options.max_pages)
    inter_page = options.max_delay * _INTER_PAGE_DELAY_FACTOR * (n - 1)
    estimated = _PER_PAGE_BUDGET_SECONDS * n + inter_page
    return max(BrowserManager.DEFAULT_OPERATION_TIMEOUT, estimated)


def _deserialize_search_params(raw_search_params: Optional[str]) -> Optional[dict]:
    """search_params JSON 문자열 역직렬화."""
    if not raw_search_params:
        return None
    try:
        return json.loads(raw_search_params)
    except (json.JSONDecodeError, TypeError):
        return None


def _is_browser_closed_error(error: Exception) -> bool:
    """브라우저 관련 closed 오류인지 확인."""
    return is_browser_closed_error(error)


class GoogleSearchWorker(BaseWorker):
    """Google 검색 큐 처리 워커.

    큐에서 pending 상태의 검색 요청을 가져와 처리합니다.
    BrowserManager.execute_with_tab()을 통해 managed tab 계약으로 탭을 획득합니다.

    Redis 큐 지원:
    - Redis 연결 시: Redis 큐에서 작업 수신 (즉각 반응)
    - Redis 미연결 시: SQLite 폴링 fallback (1초 간격)

    Attributes:
        browser_manager: BrowserManager 참조
        use_redis: Redis 큐 사용 여부
        redis_queue: Redis 큐 인스턴스
    """

    def __init__(self, browser_manager: Optional["BrowserManager"] = None):
        """GoogleSearchWorker 초기화.

        Args:
            browser_manager: 외부에서 주입받을 BrowserManager
        """
        super().__init__(
            name="google_search_worker",
            browser_manager=browser_manager
        )

        # Redis 큐 관련
        self.use_redis = False
        self.redis_queue: Optional[RedisQueue] = None
        self._redis_initialized = False

    async def _setup_redis(self):
        """Redis 큐 초기화."""
        if self._redis_initialized:
            return

        redis_client = await RedisClient.get_client()
        if redis_client:
            self.redis_queue = RedisQueue(redis_client, GOOGLE_SEARCH_QUEUE)
            self.use_redis = True
            logger.info(f"[{self.name}] Redis 큐 모드 활성화")
            await self._recover_pending_requests()
        else:
            self.use_redis = False
            logger.info(f"[{self.name}] SQLite 폴링 모드 (Redis 미연결)")

        self._redis_initialized = True

    async def _recover_pending_requests(self):
        """워커 시작 시 pending 요청을 Redis 큐에 복구."""
        if not self.redis_queue:
            logger.debug(f"[{self.name}] Redis 큐가 없어 pending 복구 스킵")
            return

        if not db_circuit.is_available():
            logger.info("[%s] DB 불가 — pending 복구 스킵", self.name)
            return

        db = SessionLocal()
        try:
            result = await recover_pending_google_searches(db)
            logger.info(
                "[%s] Google pending 복구: pending_found=%s, recovered=%s, failed_push=%s",
                self.name,
                result["pending_found"],
                result["recovered"],
                result["failed_push"],
            )
        except Exception as e:
            self._log_worker_error("pending 복구", e)
        finally:
            db.close()

    def _get_loop_interval(self) -> float:
        """메인 루프 간격 반환.

        Returns:
            float: Redis 모드 0.1초, SQLite 모드 1초
        """
        return 0.1 if self.use_redis else 1.0

    async def _main_loop_iteration(self):
        """메인 루프 한 사이클.

        Redis 큐 또는 SQLite에서 요청을 가져와 처리합니다.
        """
        # Redis 초기화 (첫 번째 호출 시)
        await self._setup_redis()

        # Redis 큐 또는 SQLite 폴링
        if self.use_redis:
            await self._safe_execute("process_redis_queue", self._process_redis_queue)
        else:
            await self._safe_execute("process_pending_queue", self._process_pending_queue)

    # ========== Redis 큐 처리 ==========

    async def _process_redis_queue(self):
        """Redis 큐에서 작업을 가져와 처리."""
        if not self.redis_queue:
            return

        job = await self.redis_queue.pop_nowait()
        if not job:
            return  # 큐가 비어있음

        queue_id = job.get("id")
        if not queue_id:
            logger.warning(f"[{self.name}] Redis 큐 메시지에 id 없음: {job}")
            return

        db = SessionLocal()
        try:
            queue_item = db.query(GoogleSearchQueue).filter(
                GoogleSearchQueue.id == queue_id
            ).first()

            if not queue_item:
                logger.warning(f"[{self.name}] Redis 큐의 요청이 DB에 없음: id={queue_id}")
                return

            # 이미 처리된 요청인지 확인
            if queue_item.status not in (
                GoogleSearchQueue.STATUS_QUEUED,
                GoogleSearchQueue.STATUS_PENDING
            ):
                logger.debug(
                    f"[{self.name}] 이미 처리된 요청: id={queue_id}, status={queue_item.status}"
                )
                return

            logger.info(
                f"[{self.name}] Redis 큐에서 검색 요청 처리: "
                f"search_id={queue_item.search_id}, query={queue_item.query}"
            )

            # processing 상태로 변경
            queue_item.status = GoogleSearchQueue.STATUS_PROCESSING
            queue_item.started_at = datetime.now()
            db.commit()

            # 검색 실행
            await self._execute_search(queue_item, db)

        except Exception as e:
            self._log_worker_error("Redis 큐 처리", e)
        finally:
            db.close()

    # ========== SQLite 폴링 (Fallback) ==========

    async def _process_pending_queue(self):
        """pending 상태의 검색 요청을 처리."""
        db = SessionLocal()
        try:
            # pending 요청 조회 (한 번에 하나씩 처리)
            pending = (
                db.query(GoogleSearchQueue)
                .filter(GoogleSearchQueue.status == "pending")
                .order_by(GoogleSearchQueue.created_at)
                .first()
            )

            if not pending:
                return

            logger.info(
                f"[{self.name}] Processing search request: "
                f"search_id={pending.search_id}, query={pending.query}"
            )

            # processing 상태로 변경
            pending.status = "processing"
            pending.started_at = datetime.now()
            db.commit()

            # 검색 실행
            await self._execute_search(pending, db)

        except Exception as e:
            self._log_worker_error("DB 폴링 큐 처리", e)
        finally:
            db.close()

    # ========== 검색 실행 (managed-tab 계약) ==========

    def _build_search_options(self, queue_item: GoogleSearchQueue) -> CrawlOptions:
        """queue_item에서 CrawlOptions를 조립한다."""
        search_params = _deserialize_search_params(queue_item.search_params)
        return CrawlOptions(
            max_pages=queue_item.max_pages or 1,
            date_filter=queue_item.date_filter,
            search_params=search_params,
        )

    async def _run_search_with_tab(
        self,
        tab: "Page",
        queue_item: GoogleSearchQueue,
        options: CrawlOptions,
        db,
    ):
        """managed tab을 받아 검색을 수행하는 execute_with_tab 콜백."""
        crawler = GoogleSearchCrawler(tab, db)
        return await self._search_with_queue_id(crawler, queue_item, options, db)

    async def _execute_search(self, queue_item: GoogleSearchQueue, db):
        """검색 요청 실행.

        BrowserManager.execute_with_tab()을 통해 managed tab 계약으로 탭을 획득한다.
        browser-closed 오류는 1회 재시도한다.
        CaptchaDetectedError는 terminal 상태로 retry 없이 즉시 실패 처리한다.

        Args:
            queue_item: 큐 아이템
            db: DB 세션
        """
        if not self.browser or not self.browser.is_initialized:
            raise RuntimeError("BrowserManager가 초기화되지 않았습니다.")

        options = self._build_search_options(queue_item)
        operation_timeout = _compute_search_operation_timeout(options)
        max_retries = 1

        for retry_count in range(max_retries + 1):
            try:
                result = await self.browser.execute_with_tab(
                    callback=lambda tab, **_kw: self._run_search_with_tab(
                        tab, queue_item, options, db
                    ),
                    service_account_id=queue_item.service_account_id,
                    target_id=queue_item.id,
                    operation_timeout=operation_timeout,
                )

                # 완료 처리
                queue_item.status = "completed"
                queue_item.completed_at = datetime.now()
                db.commit()

                # saved_search 연결 시 업데이트
                if queue_item.saved_search_id:
                    self._update_saved_search(
                        db,
                        queue_item.saved_search_id,
                        queue_item.search_id,
                        result.total_results,
                    )

                logger.info(
                    f"[{self.name}] Search completed: "
                    f"search_id={queue_item.search_id}, "
                    f"total_results={result.total_results}"
                )
                return

            except CaptchaDetectedError:
                # CAPTCHA는 terminal 상태 — retry 없이 즉시 실패
                logger.warning(
                    f"[{self.name}] CAPTCHA detected: search_id={queue_item.search_id}"
                )
                queue_item.status = "failed"
                queue_item.error_message = "CAPTCHA 감지됨. 수동 해결이 필요합니다."
                queue_item.completed_at = datetime.now()
                db.commit()
                await report_failure_alert(
                    FailureEvent(
                        source="google_search_queue",
                        entity_id=queue_item.id,
                        failure_kind="captcha_terminal",
                        error_summary=queue_item.error_message,
                        attempt=queue_item.search_id,
                        metadata={"query": queue_item.query},
                    )
                )
                return

            except Exception as e:
                if _is_browser_closed_error(e) and retry_count < max_retries:
                    logger.warning(
                        f"[{self.name}] Browser closed, retrying: "
                        f"search_id={queue_item.search_id}, "
                        f"service_account_id={queue_item.service_account_id}, "
                        f"retry_count={retry_count + 1}"
                    )
                    continue

                logger.error(
                    f"[{self.name}] Search failed: "
                    f"search_id={queue_item.search_id}, error={e}",
                    exc_info=True,
                )
                queue_item.status = "failed"
                queue_item.error_message = str(e)
                queue_item.completed_at = datetime.now()
                db.commit()
                return

    async def _search_with_queue_id(
        self,
        crawler: GoogleSearchCrawler,
        queue_item: GoogleSearchQueue,
        options: CrawlOptions,
        db,
    ):
        """큐 아이템의 search_id를 사용하여 검색 수행.

        크롤러의 기본 search() 메서드는 새 UUID를 생성하므로,
        큐의 search_id를 사용하도록 직접 구현합니다.

        Args:
            crawler: GoogleSearchCrawler 인스턴스
            queue_item: 큐 아이템
            options: 크롤링 옵션
            db: DB 세션

        Returns:
            CrawlResult: 검색 결과
        """
        from app.modules.google_search.services.crawler import (
            SearchResultData,
            CrawlResult,
            DATE_FILTERS,
        )

        search_id = queue_item.search_id
        query = queue_item.query
        started_at = datetime.now()
        all_results = []

        # 날짜 필터 변환
        tbs = DATE_FILTERS.get(options.date_filter) if options.date_filter else None

        logger.info(
            f"[{self.name}] Starting search: query='{query}', "
            f"max_pages={options.max_pages}, date_filter={options.date_filter}"
        )

        for page_num in range(options.max_pages):
            start = page_num * 10

            # URL 생성 및 페이지 이동
            url = crawler._build_url(query, start, tbs, options.search_params)

            await crawler.page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(1.5)

            # 검색 영역 대기
            try:
                from app.modules.google_search.utils.selectors import SELECTORS
                await crawler.page.wait_for_selector(
                    SELECTORS["search_area"],
                    timeout=10000
                )
            except Exception:
                logger.warning(f"[{self.name}] Search area not found on page {page_num + 1}")

            # CAPTCHA 체크
            if await crawler._check_captcha():
                raise CaptchaDetectedError("CAPTCHA 감지됨")

            # 결과 수집
            results = await crawler._scrape_results(page_num + 1)

            if not results:
                logger.info(f"[{self.name}] No results on page {page_num + 1}, stopping")
                break

            all_results.extend(results)

            # 다음 페이지 확인
            if page_num < options.max_pages - 1:
                has_next = await crawler._has_next_page()
                if not has_next:
                    break

                # 딜레이
                import random
                delay = random.uniform(options.min_delay, options.max_delay)
                await asyncio.sleep(delay)

        completed_at = datetime.now()

        # 히스토리 저장
        history = GoogleSearchHistory(
            search_id=search_id,
            query=query,
            date_filter=options.date_filter,
            max_pages=options.max_pages,
            status="completed",
            total_results=len(all_results),
            started_at=started_at,
            completed_at=completed_at,
        )
        db.add(history)

        # 이전 런 결과 조회 (신규 결과 감지용)
        prev_url_rank_map = self._get_previous_run_results(
            db, queue_item.saved_search_id, query, search_id
        )

        # exclude_keywords 추출
        exclude_keywords = []
        if options.search_params:
            exclude_keywords = options.search_params.get("exclude_keywords") or []

        # 결과 저장 (신규 여부 및 순위 변화 계산)
        new_result_count = 0
        filtered_count = 0
        for result in all_results:
            # 후처리 필터링: exclude_keywords 포함 항목 제거
            if self._should_exclude(result, exclude_keywords):
                matched = next(
                    (kw for kw in exclude_keywords if kw and kw.lower() in (
                        (result.title or "") + " " + (result.snippet or "")
                    ).lower()),
                    None,
                )
                logger.info(
                    f"[{self.name}] Excluded: '{result.title}' (keyword: {matched})"
                )
                continue

            filtered_count += 1
            is_new = result.url not in prev_url_rank_map
            rank_change = None
            prev_rank = None

            if not is_new:
                prev_rank = prev_url_rank_map[result.url]
                rank_change = prev_rank - result.rank  # 양수 = 상승, 음수 = 하락

            if is_new:
                new_result_count += 1

            record = GoogleSearchResult(
                search_id=search_id,
                query=query,
                rank=result.rank,
                title=result.title,
                url=result.url,
                display_url=result.display_url,
                snippet=result.snippet,
                publish_date=result.publish_date,
                date_filter=options.date_filter,
                page_number=result.page_number,
                is_new=is_new,
                rank_change=rank_change,
                prev_rank=prev_rank,
            )
            db.add(record)

        # 필터링 후 실제 저장 개수를 queue_item에 반영
        queue_item.result_count = filtered_count

        db.commit()

        # 신규 결과 알림 발송
        if new_result_count > 0 and queue_item.saved_search_id:
            await self._send_new_result_notification(
                db, queue_item.saved_search_id, query, new_result_count, search_id
            )

        return CrawlResult(
            search_id=search_id,
            query=query,
            results=all_results,
            total_results=len(all_results),
            status="completed",
            started_at=started_at,
            completed_at=completed_at,
        )

    def _update_saved_search(
        self,
        db,
        saved_search_id: int,
        search_id: str,
        total_results: int,
    ):
        """저장된 검색 조건 업데이트.

        Args:
            db: DB 세션
            saved_search_id: 저장된 검색 ID
            search_id: 검색 세션 ID
            total_results: 결과 수
        """
        try:
            saved = db.query(GoogleSavedSearch).filter_by(id=saved_search_id).first()
            if saved:
                saved.last_search_id = search_id
                saved.last_run_at = datetime.now()
                saved.last_result_count = total_results
                saved.updated_at = datetime.now()
                db.commit()
                logger.debug(
                    f"[{self.name}] Updated saved search: id={saved_search_id}"
                )
        except Exception as e:
            logger.warning(
                f"[{self.name}] Failed to update saved search: {e}"
            )

    def _get_previous_run_results(
        self,
        db,
        saved_search_id: Optional[int],
        query: str,
        current_search_id: str,
    ) -> dict:
        """이전 런의 결과 URL→rank 매핑 조회.

        Args:
            db: DB 세션
            saved_search_id: 저장된 검색 ID (없으면 query로 조회)
            query: 검색 키워드
            current_search_id: 현재 검색 ID (제외용)

        Returns:
            dict: {url: rank} 매핑
        """
        try:
            # 직전 런의 search_id 찾기
            if saved_search_id:
                prev_queue = (
                    db.query(GoogleSearchQueue)
                    .filter(
                        GoogleSearchQueue.saved_search_id == saved_search_id,
                        GoogleSearchQueue.status == "completed",
                        GoogleSearchQueue.search_id != current_search_id,
                    )
                    .order_by(GoogleSearchQueue.completed_at.desc())
                    .first()
                )
            else:
                prev_queue = (
                    db.query(GoogleSearchQueue)
                    .filter(
                        GoogleSearchQueue.query == query,
                        GoogleSearchQueue.status == "completed",
                        GoogleSearchQueue.search_id != current_search_id,
                    )
                    .order_by(GoogleSearchQueue.completed_at.desc())
                    .first()
                )

            if not prev_queue:
                return {}

            # 이전 런의 결과 조회
            prev_results = db.query(GoogleSearchResult).filter(
                GoogleSearchResult.search_id == prev_queue.search_id
            ).all()

            return {r.url: r.rank for r in prev_results}

        except Exception as e:
            logger.warning(f"[{self.name}] Failed to get previous run results: {e}")
            return {}

    def _should_exclude(self, result, exclude_keywords) -> bool:
        """결과를 제외 키워드 기준으로 필터링할지 판단.

        Args:
            result: SearchResultData 인스턴스
            exclude_keywords: 제외 키워드 목록 (None 또는 빈 리스트면 항상 False)

        Returns:
            True면 이 결과를 제외
        """
        if not exclude_keywords:
            return False
        text = ((result.title or "") + " " + (result.snippet or "")).lower()
        return any(kw and kw.lower() in text for kw in exclude_keywords)

    async def _send_new_result_notification(
        self,
        db,
        saved_search_id: int,
        query: str,
        new_count: int,
        search_id: str,
    ):
        """신규 결과 알림 발송.

        Args:
            db: DB 세션
            saved_search_id: 저장된 검색 ID
            query: 검색 키워드
            new_count: 신규 결과 수
            search_id: 검색 세션 ID
        """
        try:
            saved = db.query(GoogleSavedSearch).filter_by(id=saved_search_id).first()
            if not saved or not saved.notify_on_new:
                return

            from app.shared.notification import NotificationService

            message = (
                f"[Google 검색] {saved.name} 신규 결과 {new_count}건\n"
                f"검색어: {query}\n"
                f"search_id: {search_id}"
            )
            await NotificationService().send_notification_message(
                message,
                send_desktop=False,
                force_send=True,
                send_telegram=True,
            )

            logger.info(
                f"[{self.name}] New result notification sent: "
                f"saved_search={saved.name}, new_count={new_count}, search_id={search_id}"
            )

        except Exception as e:
            logger.warning(f"[{self.name}] Failed to send notification: {e}")

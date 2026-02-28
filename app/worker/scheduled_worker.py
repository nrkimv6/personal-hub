"""
스케줄 기반 크롤링 워커.

TaskSchedule 설정에 따라 정해진 시간에 크롤링을 자동으로 수행합니다.

실행 방법:
    python -m app.worker.scheduled_worker

주요 기능:
    - 스케줄 설정에 따른 자동 피드 크롤링
    - TimeWindow 기반 실행 시간 관리
    - 최소 간격 제한 준수
    - Google 검색 스케줄 지원
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from app.worker.crawl_worker_base import CrawlWorkerBase
from app.database import SessionLocal
from app.models import ServiceAccount, TaskSchedule, TaskScheduleRun
from app.models.google_search import GoogleSearchQueue, GoogleSearchHistory, GoogleSavedSearch

from app.services.task_schedule_service import TaskScheduleService
from app.modules.instagram.services.crawl_service import CrawlService
from app.utils.error_utils import format_error_message
from app.modules.instagram.services.scheduler import InstagramScheduler
from app.modules.instagram.services.crawler import InstagramCrawler
from app.modules.instagram.models.schemas import TimeWindow
from app.modules.writing.worker.writing_worker import WritingWorker
from app.modules.writing.worker.topic_extract_worker import TopicExtractWorker

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


def parse_time_windows(raw_windows: list) -> Optional[List[TimeWindow]]:
    """TimeWindow 목록 파싱. 빈 배열이면 None 반환.

    start_hour/end_hour 형식도 start/end로 변환 지원.
    list 형식([start, end])도 dict 형식으로 변환 지원.
    """
    if not raw_windows:
        return None

    result = []
    logger = logging.getLogger(__name__)

    for tw in raw_windows:
        # list 형식 처리: ["09:00", "12:00"] -> {"start": "09:00", "end": "12:00"}
        if isinstance(tw, list):
            if len(tw) == 2:
                tw = {"start": tw[0], "end": tw[1]}
            else:
                logger.warning(f"Invalid time window list format (expected 2 elements): {tw}")
                continue

        # start_hour/end_hour 형식 변환
        if "start_hour" in tw and "start" not in tw:
            tw = {
                "start": f"{tw['start_hour']:02d}:00",
                "end": f"{tw['end_hour']:02d}:00"
            }
        result.append(TimeWindow(**tw))

    return result if result else None


class ScheduledCrawlWorker(CrawlWorkerBase):
    """스케줄 기반 Instagram 피드 크롤링 워커.

    TaskSchedule 설정에 따라 정해진 시간에
    자동으로 Instagram 피드를 크롤링합니다.

    Attributes:
        check_interval: 스케줄 확인 간격 (초)
    """

    def __init__(self, check_interval: int = 30, browser_manager=None):
        """ScheduledCrawlWorker 초기화.

        Args:
            check_interval: 스케줄 확인 간격 (초). 기본 30초.
            browser_manager: 외부에서 주입받을 BrowserManager (None이면 자체 생성)
        """
        super().__init__(
            name="scheduled_worker",
            worker_type="scheduled",
            browser_manager=browser_manager
        )
        self.check_interval = check_interval

    def _get_loop_interval(self) -> float:
        """메인 루프 간격 반환."""
        return 1.0  # 1초마다 체크 (shutdown 빠른 반응)

    async def _main_loop_iteration(self):
        """메인 루프 한 사이클.

        스케줄 설정을 확인하고, 실행 시간이 되면 크롤링을 시작합니다.
        """
        # 완료된 태스크 정리
        self._cleanup_completed_tasks()

        # 오래된 running 상태 실행 정리 (5분마다 실행)
        if not hasattr(self, '_last_stale_cleanup'):
            self._last_stale_cleanup = datetime.now()

        if (datetime.now() - self._last_stale_cleanup).total_seconds() >= 300:
            self._cleanup_stale_requests()
            self._last_stale_cleanup = datetime.now()

        # 스케줄 기반 실행 디스패치
        await self._dispatch_scheduled_runs()

        # 02:10 안전망: 미처리 plan archive LLM 큐 등록
        await self._safe_execute("check_plan_archive_schedule", self._check_plan_archive_schedule)

    def _cleanup_stale_requests(self):
        """오래된 running 상태 실행 정리."""
        db = SessionLocal()
        try:
            schedule_service = TaskScheduleService(db)
            cleaned = schedule_service.cleanup_stale_runs(timeout_minutes=30)
            if cleaned > 0:
                logger.info(f"[{self.name}] {cleaned}개의 오래된 running 실행 정리 완료")
        except Exception as e:
            logger.error(f"[{self.name}] Stale run 정리 오류: {e}")
        finally:
            db.close()

    async def _dispatch_scheduled_runs(self):
        """스케줄 설정을 확인하고 실행 시간이면 크롤링을 시작합니다."""
        db = SessionLocal()
        try:
            schedule_service = TaskScheduleService(db)

            # Instagram feed 타입의 활성 스케줄 조회
            instagram_schedules = schedule_service.get_schedules_by_type(
                TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
                enabled_only=True
            )
            for schedule in instagram_schedules:
                await self._process_schedule(db, schedule, schedule_service)

            # Google search 타입의 활성 스케줄 조회
            google_schedules = schedule_service.get_schedules_by_type(
                TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH,
                enabled_only=True
            )
            for schedule in google_schedules:
                await self._process_google_search_schedule(db, schedule, schedule_service)

            # Writing task 타입의 활성 스케줄 조회
            writing_task_schedules = schedule_service.get_schedules_by_type(
                TaskSchedule.TARGET_TYPE_WRITING_TASK,
                enabled_only=True
            )
            for schedule in writing_task_schedules:
                await self._process_writing_schedule(db, schedule, schedule_service)

            # Writing source collect 타입의 활성 스케줄 조회
            writing_source_schedules = schedule_service.get_schedules_by_type(
                TaskSchedule.TARGET_TYPE_WRITING_SOURCE_COLLECT,
                enabled_only=True
            )
            for schedule in writing_source_schedules:
                await self._process_writing_source_schedule(db, schedule, schedule_service)

            # Keyword analysis 타입의 활성 스케줄 조회
            keyword_schedules = schedule_service.get_schedules_by_type(
                TaskSchedule.TARGET_TYPE_KEYWORD_ANALYSIS,
                enabled_only=True
            )
            for schedule in keyword_schedules:
                await self._process_keyword_analysis_schedule(db, schedule, schedule_service)

            # Topic extract 타입의 활성 스케줄 조회
            topic_extract_schedules = schedule_service.get_schedules_by_type(
                TaskSchedule.TARGET_TYPE_TOPIC_EXTRACT,
                enabled_only=True
            )
            for schedule in topic_extract_schedules:
                await self._process_topic_extract_schedule(db, schedule, schedule_service)

            # Report 타입의 활성 스케줄 조회
            report_schedules = schedule_service.get_schedules_by_type(
                TaskSchedule.TARGET_TYPE_REPORT,
                enabled_only=True
            )
            for schedule in report_schedules:
                await self._process_report_schedule(db, schedule, schedule_service)

            # pytest_run 타입의 활성 스케줄 조회
            pytest_schedules = schedule_service.get_schedules_by_type(
                TaskSchedule.TARGET_TYPE_PYTEST_RUN,
                enabled_only=True
            )
            for schedule in pytest_schedules:
                await self._process_pytest_schedule(db, schedule, schedule_service)

        except Exception as e:
            logger.error(f"[{self.name}] 스케줄 디스패치 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _check_plan_archive_schedule(self):
        """02:10 ± 5분 안전망 — 미처리 plan archive LLM 큐 등록"""
        now = datetime.now()
        # 02:10 ± 5분 범위 확인
        target_minutes = 2 * 60 + 10  # 130분
        current_minutes = now.hour * 60 + now.minute
        if abs(current_minutes - target_minutes) > 5:
            return

        # 오늘 이미 실행했는지 확인
        today_key = f"_plan_archive_schedule_last_run_{now.date()}"
        if getattr(self, today_key, None):
            return

        count = await asyncio.get_event_loop().run_in_executor(None, self._process_unprocessed_plans)
        setattr(self, today_key, True)
        if count > 0:
            logger.info(f"[{self.name}] plan archive 안전망: {count}개 LLM 큐 등록")

    def _process_unprocessed_plans(self) -> int:
        """DB에서 미처리 plan_records 조회 → LLM 큐 등록.

        Returns:
            등록된 LLMRequest 건수
        """
        from app.models.plan_record import PlanRecord
        from app.modules.claude_worker.models.llm_request import LLMRequest
        from app.modules.claude_worker.services.plan_analyze_handler import build_plan_analyze_prompt
        from sqlalchemy import and_
        from pathlib import Path

        db = SessionLocal()
        try:
            records = db.query(PlanRecord).filter(
                and_(
                    PlanRecord.llm_processed_at.is_(None),
                    PlanRecord.archived_at.isnot(None),
                )
            ).order_by(PlanRecord.archived_at.asc()).all()

            if not records:
                return 0

            # 기존 pending 중복 체크
            existing_pending = {
                row[0]
                for row in db.query(LLMRequest.caller_id).filter(
                    and_(
                        LLMRequest.caller_type == "plan_archive_analyze",
                        LLMRequest.status == "pending",
                    )
                ).all()
            }

            inserted = 0
            for record in records:
                if record.filename_hash in existing_pending:
                    continue

                file_content = ""
                try:
                    fp = Path(record.file_path)
                    if fp.exists():
                        file_content = fp.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass

                prompt = build_plan_analyze_prompt(
                    file_content=file_content,
                    filename=Path(record.file_path).name,
                )
                llm_req = LLMRequest(
                    caller_type="plan_archive_analyze",
                    caller_id=record.filename_hash,
                    prompt=prompt,
                    queue_name="utility",
                    requested_by="scheduler",
                )
                db.add(llm_req)
                inserted += 1

            if inserted > 0:
                db.commit()
            return inserted
        except Exception as e:
            logger.error(f"_process_unprocessed_plans error: {e}", exc_info=True)
            db.rollback()
            return 0
        finally:
            db.close()

    async def _process_schedule(
        self,
        db,
        schedule: TaskSchedule,
        schedule_service: TaskScheduleService
    ):
        """개별 스케줄 처리."""
        try:
            config = schedule.get_target_config()
            service_account_id = config.get("service_account_id")

            if not service_account_id:
                return

            # schedule_value에서 스케줄 설정 추출 (time_windows, daily_runs)
            schedule_value = {}
            if schedule.schedule_value:
                try:
                    schedule_value = json.loads(schedule.schedule_value)
                except json.JSONDecodeError:
                    pass

            # 스케줄 설정은 schedule_value에서 읽기 (UI와 동일한 소스)
            time_windows = parse_time_windows(schedule_value.get("time_windows", []))
            daily_runs = schedule_value.get("daily_runs", 3)

            # 크롤링 설정은 target_config에서 읽기
            min_interval = config.get("min_interval_hours", 2)

            scheduler = InstagramScheduler(
                daily_runs=daily_runs,
                time_windows=time_windows,
            )

            # 마지막 실행 시간 조회
            last_run = schedule_service.get_latest_run(schedule.id)
            last_run_time = last_run.started_at if last_run else None

            if scheduler.should_run_now(
                last_run=last_run_time,
                min_interval_hours=min_interval,
            ):
                logger.info(f"[{self.name}] 스케줄 실행 시간 도래: schedule_id={schedule.id}")

                # 이미 활성 실행이 있는지 확인
                if schedule_service.has_active_run(schedule.id):
                    logger.info(f"[{self.name}] 이미 활성 실행 존재, 스킵")
                    return

                # 실행 시작
                run = schedule_service.start_run(
                    schedule_id=schedule.id,
                    worker_id=self.name,
                    config_snapshot=config
                )

                task_name = f"schedule_{schedule.id}_run_{run.id}"
                if not self._is_task_running(task_name):
                    self._create_task(
                        self._execute_feed_crawl(schedule, run, service_account_id),
                        task_name
                    )
                    logger.info(f"[{self.name}] 스케줄 피드 크롤링 태스크 시작: run_id={run.id}")

        except Exception as e:
            logger.error(f"[{self.name}] 스케줄 처리 오류: schedule_id={schedule.id}, error={e}", exc_info=True)

    async def _execute_feed_crawl(
        self,
        schedule: TaskSchedule,
        run: TaskScheduleRun,
        service_account_id: int
    ):
        """Instagram 피드 크롤링 실행.

        Args:
            schedule: 크롤링 스케줄
            run: 실행 기록
            service_account_id: 계정 ID
        """
        db = SessionLocal()
        max_retries = 3
        retry_count = 0

        try:
            schedule_service = TaskScheduleService(db)
            crawl_service = CrawlService(db)

            while retry_count <= max_retries:
                try:
                    account = db.query(ServiceAccount).filter(
                        ServiceAccount.id == service_account_id
                    ).first()
                    if not account:
                        schedule_service.fail_run(run.id, "계정을 찾을 수 없음")
                        logger.warning(f"[{self.name}] 계정 없음: service_account_id={service_account_id}")
                        return

                    self._update_worker_state("crawling", account.identifier)

                    # BrowserManager를 통한 탭 획득 및 크롤링 실행
                    # Instagram 크롤링은 최대 500개까지 수집 가능하므로 충분한 시간 필요
                    result = await self.execute_with_tab(
                        callback=self._crawl_with_tab,
                        service_account_id=account.id,
                        operation_timeout=3600.0,  # 1시간 타임아웃
                        schedule=schedule,
                        run=run,
                        account=account,
                        db=db,
                        schedule_service=schedule_service,
                        crawl_service=crawl_service,
                    )

                    if result:
                        return  # 성공적으로 완료

                except Exception as e:
                    if self.is_browser_closed_error(e) and retry_count < max_retries:
                        retry_count += 1
                        logger.warning(
                            f"[{self.name}] 브라우저 closed 에러 감지, 재시도 ({retry_count}/{max_retries}): {e}"
                        )
                        # 브라우저 재초기화
                        if self.browser and self.browser.is_initialized:
                            await self.browser.cleanup()
                            self._browser_initialized = False
                        continue

                    schedule_service.fail_run(run.id, format_error_message(e))
                    logger.error(f"[{self.name}] 크롤링 예외: {format_error_message(e)}", exc_info=True)
                    return

        except Exception as e:
            logger.error(f"[{self.name}] 피드 크롤링 실패: run_id={run.id}, error={format_error_message(e)}", exc_info=True)
            try:
                schedule_service = TaskScheduleService(db)
                schedule_service.fail_run(run.id, format_error_message(e))
            except Exception:
                pass
        finally:
            self._update_worker_state("idle")
            db.close()

    async def _crawl_with_tab(
        self,
        tab: "Page",
        schedule: TaskSchedule,
        run: TaskScheduleRun,
        account: ServiceAccount,
        db,
        schedule_service: TaskScheduleService,
        crawl_service: CrawlService,
    ) -> bool:
        """탭을 사용하여 피드 크롤링을 수행합니다.

        Args:
            tab: Playwright Page 객체
            schedule: 크롤링 스케줄
            run: 실행 기록
            account: 계정 정보
            db: DB 세션
            schedule_service: 스케줄 서비스
            crawl_service: 크롤링 서비스

        Returns:
            성공 여부
        """
        logger.info(f"[{self.name}] 인스타그램 피드 페이지로 이동 중...")
        await tab.goto("https://www.instagram.com/", wait_until="domcontentloaded")
        await tab.wait_for_timeout(2000)
        logger.info(f"[{self.name}] 인스타그램 페이지 로드 완료: {tab.url}")

        is_logged_in = await self._check_instagram_login(tab)
        if not is_logged_in:
            account.is_logged_in = False
            db.commit()
            schedule_service.fail_run(run.id, "Instagram 로그인 필요")
            logger.warning(f"[{self.name}] Instagram 로그인 필요: account={account.identifier}")
            return False
        else:
            account.is_logged_in = True
            db.commit()

        crawler = InstagramCrawler(tab)
        logger.info(f"[{self.name}] InstagramCrawler 생성 완료, 크롤링 시작...")

        # CrawlService.run_crawl 사용 (TaskScheduleRun 생성)
        crawl_run = await crawl_service.run_crawl(
            crawler=crawler,
            service_account_id=account.id,
        )

        self._update_worker_state("crawling", account.identifier, run.id)

        crawl_success = crawl_run.status == TaskScheduleRun.STATUS_COMPLETED
        logger.info(
            f"[{self.name}] 크롤링 완료: success={crawl_success}, "
            f"collected={crawl_run.collected_count}, new={crawl_run.saved_count}"
        )

        # TaskScheduleRun 업데이트
        if crawl_success:
            schedule_service.complete_run(
                run.id,
                collected_count=crawl_run.collected_count,
                saved_count=crawl_run.saved_count,
                stop_reason=crawl_run.stop_reason
            )
            schedule_service.update_schedule_after_run(run.schedule_id)
            logger.info(
                f"[{self.name}] 크롤링 완료: run_id={run.id}, "
                f"collected={crawl_run.collected_count}, new={crawl_run.saved_count}"
            )
        else:
            schedule_service.fail_run(run.id, crawl_run.error_message or "크롤링 실패")
            logger.warning(f"[{self.name}] 크롤링 실패: {crawl_run.error_message}")

        return crawl_success

    async def _check_instagram_login(self, page: "Page") -> bool:
        """Instagram 로그인 상태 확인.

        Args:
            page: Playwright Page 객체

        Returns:
            로그인 여부
        """
        try:
            login_button = await page.query_selector('a[href="/accounts/login/"]')
            if login_button:
                return False

            login_indicators = [
                'a[href*="/direct/inbox/"]',
                'svg[aria-label="홈"]',
                'svg[aria-label="Home"]',
                'article',
            ]
            for selector in login_indicators:
                elem = await page.query_selector(selector)
                if elem:
                    return True

            return False
        except Exception as e:
            logger.warning(f"[{self.name}] Instagram 로그인 상태 확인 실패: {e}")
            return False

    # =====================================
    # Google 검색 스케줄 처리
    # =====================================

    async def _process_google_search_schedule(
        self,
        db,
        schedule: TaskSchedule,
        schedule_service: TaskScheduleService
    ):
        """Google 검색 스케줄 처리.

        Args:
            db: DB 세션
            schedule: 크롤링 스케줄
            schedule_service: 스케줄 서비스
        """
        try:
            config = schedule.get_target_config()
            saved_search_id = config.get("saved_search_id")

            if not saved_search_id:
                logger.warning(f"[{self.name}] saved_search_id 없음: schedule_id={schedule.id}")
                return

            # 타임 윈도우 설정 (빈 배열이면 None으로 처리하여 기본값 사용)
            time_windows = parse_time_windows(config.get("time_windows", []))
            daily_runs = config.get("daily_runs", 1)
            min_interval = config.get("min_interval_hours", 1)

            scheduler = InstagramScheduler(
                daily_runs=daily_runs,
                time_windows=time_windows,
            )

            # 마지막 실행 시간 조회
            last_run = schedule_service.get_latest_run(schedule.id)
            last_run_time = last_run.started_at if last_run else None

            if scheduler.should_run_now(
                last_run=last_run_time,
                min_interval_hours=min_interval,
            ):
                logger.info(f"[{self.name}] Google 검색 스케줄 실행 시간 도래: schedule_id={schedule.id}")

                # 이미 활성 실행이 있는지 확인
                if schedule_service.has_active_run(schedule.id):
                    logger.info(f"[{self.name}] 이미 활성 실행 존재, 스킵")
                    return

                # 실행 시작
                run = schedule_service.start_run(
                    schedule_id=schedule.id,
                    worker_id=self.name,
                    config_snapshot=config
                )

                task_name = f"google_schedule_{schedule.id}_run_{run.id}"
                if not self._is_task_running(task_name):
                    # Note: schedule/run 객체 대신 ID를 전달하여 세션 바인딩 오류 방지
                    self._create_task(
                        self._execute_google_search(schedule.id, run.id, saved_search_id),
                        task_name
                    )
                    logger.info(f"[{self.name}] Google 검색 스케줄 태스크 시작: run_id={run.id}")

        except Exception as e:
            logger.error(f"[{self.name}] Google 검색 스케줄 처리 오류: schedule_id={schedule.id}, error={e}", exc_info=True)

    async def _execute_google_search(
        self,
        schedule_id: int,
        run_id: int,
        saved_search_id: int
    ):
        """Google 검색 실행 (비동기 큐 방식).

        검색 요청을 큐에 추가하고 즉시 완료 처리합니다.
        실제 검색은 GoogleSearchWorker가 비동기로 처리합니다.

        Args:
            schedule_id: 스케줄 ID
            run_id: 실행 기록 ID
            saved_search_id: 저장된 검색 ID
        """
        db = SessionLocal()
        try:
            schedule_service = TaskScheduleService(db)

            # 저장된 검색 조회
            saved_search = db.query(GoogleSavedSearch).filter_by(id=saved_search_id).first()
            if not saved_search:
                schedule_service.fail_run(run_id, "저장된 검색을 찾을 수 없습니다")
                logger.warning(f"[{self.name}] 저장된 검색 없음: saved_search_id={saved_search_id}")
                return

            self._update_worker_state("searching", saved_search.name)

            # GoogleSearchQueue에 추가 (스케줄 실행 추적을 위한 메타데이터 포함)
            search_id = str(uuid.uuid4())
            queue_item = GoogleSearchQueue(
                search_id=search_id,
                query=saved_search.query,
                date_filter=saved_search.date_filter,
                max_pages=saved_search.max_pages or 1,
                service_account_id=saved_search.service_account_id,
                saved_search_id=saved_search_id,
                schedule_id=schedule.id,
                status="pending"
            )
            db.add(queue_item)
            db.commit()

            logger.info(
                f"[{self.name}] Google 검색 큐에 추가: "
                f"search_id={search_id}, query={saved_search.query}"
            )

            # 즉시 완료 처리 (비동기 - 실제 결과는 GoogleSearchWorker가 처리)
            schedule_service.complete_run(
                run_id,
                collected_count=0,
                saved_count=0,
                stop_reason=TaskScheduleRun.STOP_REASON_SEARCH_QUEUED
            )
            schedule_service.update_schedule_after_run(schedule_id)
            logger.info(f"[{self.name}] Google 검색 스케줄 완료 (큐 추가): run_id={run_id}")

        except Exception as e:
            logger.error(f"[{self.name}] Google 검색 실행 실패: run_id={run_id}, error={format_error_message(e)}", exc_info=True)
            try:
                schedule_service = TaskScheduleService(db)
                schedule_service.fail_run(run_id, format_error_message(e))
            except Exception:
                pass
        finally:
            self._update_worker_state("idle")
            db.close()

    async def _wait_for_search_completion(
        self,
        search_id: str,
        timeout: int = 300
    ) -> dict:
        """검색 완료 대기 (최대 5분).

        Args:
            search_id: 검색 세션 ID
            timeout: 타임아웃 (초)

        Returns:
            dict: {"status": "completed"|"failed", "total_results": int, "error_message": str}
        """
        start = datetime.now()
        logger.info(f"[{self.name}] 검색 완료 대기 시작: search_id={search_id}, timeout={timeout}s")

        while (datetime.now() - start).total_seconds() < timeout:
            db = SessionLocal()
            try:
                # 큐 상태 확인
                queue = db.query(GoogleSearchQueue).filter_by(search_id=search_id).first()

                if queue and queue.status in ["completed", "failed"]:
                    elapsed = int((datetime.now() - start).total_seconds())
                    logger.info(
                        f"[{self.name}] 검색 완료 확인: search_id={search_id}, "
                        f"status={queue.status}, elapsed={elapsed}s"
                    )
                    history = db.query(GoogleSearchHistory).filter_by(search_id=search_id).first()
                    return {
                        "status": queue.status,
                        "total_results": history.total_results if history else 0,
                        "error_message": queue.error_message
                    }
            finally:
                db.close()

            await asyncio.sleep(2)

        # 타임아웃 발생
        logger.warning(
            f"[{self.name}] 검색 완료 대기 타임아웃: search_id={search_id}, timeout={timeout}s"
        )
        return {"status": "failed", "error_message": "Timeout"}

    # =====================================
    # Writing Source 수집 스케줄 처리
    # =====================================

    async def _process_writing_source_schedule(
        self,
        db,
        schedule: TaskSchedule,
        schedule_service: TaskScheduleService
    ):
        """Writing Source 수집 스케줄 처리.

        Args:
            db: DB 세션
            schedule: 크롤링 스케줄
            schedule_service: 스케줄 서비스
        """
        try:
            config = schedule.get_target_config()

            # 수동 실행 요청 확인 (API에서 즉시 실행 버튼 클릭 시)
            manual_run = schedule_service.get_pending_manual_run(schedule.id)
            if manual_run:
                task_name = f"writing_source_{schedule.id}_run_{manual_run.id}"
                if not self._is_task_running(task_name):
                    # worker_id 업데이트
                    manual_run.worker_id = self.name
                    db.commit()
                    self._create_task(
                        self._execute_writing_source_collect(manual_run, config),
                        task_name
                    )
                    logger.info(f"[{self.name}] 수동 Writing Source 수집 태스크 시작: run_id={manual_run.id}")
                return

            # 타임 윈도우 설정 (빈 배열이면 None으로 처리하여 기본값 사용)
            time_windows = parse_time_windows(config.get("time_windows", []))
            daily_runs = config.get("daily_runs", 1)
            min_interval = config.get("min_interval_hours", 20)  # 기본 20시간 (하루 1회)

            scheduler = InstagramScheduler(
                daily_runs=daily_runs,
                time_windows=time_windows,
            )

            # 마지막 실행 시간 조회
            last_run = schedule_service.get_latest_run(schedule.id)
            last_run_time = last_run.started_at if last_run else None

            if scheduler.should_run_now(
                last_run=last_run_time,
                min_interval_hours=min_interval,
            ):
                logger.info(f"[{self.name}] Writing Source 수집 스케줄 실행 시간 도래: schedule_id={schedule.id}")

                # 이미 활성 실행이 있는지 확인
                if schedule_service.has_active_run(schedule.id):
                    logger.info(f"[{self.name}] 이미 활성 실행 존재, 스킵")
                    return

                # 실행 시작
                run = schedule_service.start_run(
                    schedule_id=schedule.id,
                    worker_id=self.name,
                    config_snapshot=config
                )

                task_name = f"writing_source_{schedule.id}_run_{run.id}"
                if not self._is_task_running(task_name):
                    self._create_task(
                        self._execute_writing_source_collect(run, config),
                        task_name
                    )
                    logger.info(f"[{self.name}] Writing Source 수집 태스크 시작: run_id={run.id}")

        except Exception as e:
            logger.error(f"[{self.name}] Writing Source 스케줄 처리 오류: schedule_id={schedule.id}, error={e}", exc_info=True)

    async def _execute_writing_source_collect(
        self,
        run: TaskScheduleRun,
        config: dict
    ):
        """Writing Source 수집 실행 (RSS, 위키문헌).

        Args:
            run: 실행 기록
            config: 수집 설정
        """
        db = SessionLocal()
        try:
            schedule_service = TaskScheduleService(db)

            from app.modules.writing.services.writing_service import WritingService
            writing_service = WritingService(db)

            self._update_worker_state("collecting", "writing_sources")

            total_collected = 0
            errors = []

            # 1. RSS 수집
            if config.get("collect_rss", True):
                try:
                    logger.info(f"[{self.name}] RSS 수집 시작...")
                    rss_result = await writing_service.collect_from_feeds(
                        min_length=config.get("rss_min_length", 300),
                        max_length=config.get("rss_max_length", 3000),
                    )
                    total_collected += rss_result.get("collected", 0)
                    logger.info(f"[{self.name}] RSS 수집 완료: {rss_result.get('collected', 0)}건")
                except Exception as e:
                    errors.append(f"RSS: {format_error_message(e)}")
                    logger.error(f"[{self.name}] RSS 수집 오류: {e}")

            # 2. 위키문헌 수집
            if config.get("collect_wikisource", True):
                try:
                    logger.info(f"[{self.name}] 위키문헌 수집 시작...")
                    wiki_result = await writing_service.collect_from_wikisource(
                        min_length=config.get("wiki_min_length", 200),
                        max_length=config.get("wiki_max_length", 10000),
                    )
                    total_collected += wiki_result.get("collected", 0)
                    logger.info(f"[{self.name}] 위키문헌 수집 완료: {wiki_result.get('collected', 0)}건")
                except Exception as e:
                    errors.append(f"Wikisource: {format_error_message(e)}")
                    logger.error(f"[{self.name}] 위키문헌 수집 오류: {e}")

            # 3. 검색 API 수집 (API 키가 설정된 경우)
            if config.get("collect_search", False):
                try:
                    logger.info(f"[{self.name}] 검색 API 수집 시작...")
                    search_result = await writing_service.collect_from_searches(
                        min_length=config.get("search_min_length", 100),
                        max_length=config.get("search_max_length", 5000),
                        max_queries=config.get("search_max_queries", 10),
                    )
                    total_collected += search_result.get("collected", 0)
                    logger.info(f"[{self.name}] 검색 API 수집 완료: {search_result.get('collected', 0)}건")
                except Exception as e:
                    errors.append(f"Search: {format_error_message(e)}")
                    logger.error(f"[{self.name}] 검색 API 수집 오류: {e}")

            # 실행 완료
            if errors:
                error_msg = "; ".join(errors)
                if total_collected > 0:
                    # 일부 성공
                    schedule_service.complete_run(
                        run.id,
                        collected_count=total_collected,
                        saved_count=total_collected,
                        stop_reason=f"partial_success: {error_msg}"
                    )
                else:
                    schedule_service.fail_run(run.id, error_msg)
            else:
                schedule_service.complete_run(
                    run.id,
                    collected_count=total_collected,
                    saved_count=total_collected,
                    stop_reason="completed"
                )

            schedule_service.update_schedule_after_run(run.schedule_id)
            logger.info(f"[{self.name}] Writing Source 수집 완료: run_id={run.id}, total={total_collected}")

        except Exception as e:
            logger.error(f"[{self.name}] Writing Source 수집 실패: run_id={run.id}, error={format_error_message(e)}", exc_info=True)
            try:
                schedule_service = TaskScheduleService(db)
                schedule_service.fail_run(run.id, format_error_message(e))
            except Exception:
                pass
        finally:
            self._update_worker_state("idle")
            db.close()

    # =====================================
    # Writing Task 스케줄 처리
    # =====================================

    async def _process_writing_schedule(
        self,
        db,
        schedule: TaskSchedule,
        schedule_service: TaskScheduleService
    ):
        """Writing task 스케줄 처리.

        Args:
            db: DB 세션
            schedule: 크롤링 스케줄
            schedule_service: 스케줄 서비스
        """
        try:
            config = schedule.get_target_config()

            # 타임 윈도우 설정 (빈 배열이면 None으로 처리하여 기본값 사용)
            time_windows = parse_time_windows(config.get("time_windows", []))
            daily_runs = config.get("daily_runs", 1)
            min_interval = config.get("min_interval_hours", 20)  # 기본 20시간 간격

            scheduler = InstagramScheduler(
                daily_runs=daily_runs,
                time_windows=time_windows,
            )

            # 마지막 실행 시간 조회
            last_run = schedule_service.get_latest_run(schedule.id)
            last_run_time = last_run.started_at if last_run else None

            if scheduler.should_run_now(
                last_run=last_run_time,
                min_interval_hours=min_interval,
            ):
                logger.info(f"[{self.name}] Writing task 스케줄 실행 시간 도래: schedule_id={schedule.id}")

                # 이미 활성 실행이 있는지 확인
                if schedule_service.has_active_run(schedule.id):
                    logger.info(f"[{self.name}] 이미 활성 실행 존재, 스킵")
                    return

                # 실행 시작
                run = schedule_service.start_run(
                    schedule_id=schedule.id,
                    worker_id=self.name,
                    config_snapshot=config
                )

                task_name = f"writing_schedule_{schedule.id}_run_{run.id}"
                if not self._is_task_running(task_name):
                    self._create_task(
                        self._execute_writing_task(schedule, run),
                        task_name
                    )
                    logger.info(f"[{self.name}] Writing task 태스크 시작: run_id={run.id}")

        except Exception as e:
            logger.error(f"[{self.name}] Writing task 스케줄 처리 오류: schedule_id={schedule.id}, error={e}", exc_info=True)

    async def _execute_writing_task(
        self,
        schedule: TaskSchedule,
        run: TaskScheduleRun
    ):
        """Writing task 실행.

        Args:
            schedule: 스케줄
            run: 실행 기록
        """
        db = SessionLocal()
        try:
            schedule_service = TaskScheduleService(db)

            self._update_worker_state("writing", f"schedule_{schedule.id}")

            # WritingWorker 실행 (동기 호출을 별도 스레드에서 실행)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._run_writing_worker_sync,
                schedule,
                run
            )

            if result.get("error"):
                schedule_service.fail_run(run.id, result["error"])
                logger.error(f"[{self.name}] Writing task 실패: {result['error']}")
            else:
                schedule_service.complete_run(
                    run.id,
                    collected_count=result.get("total", 0),
                    saved_count=result.get("success", 0),
                    stop_reason="completed"
                )
                schedule_service.update_schedule_after_run(run.schedule_id)
                logger.info(
                    f"[{self.name}] Writing task 완료: run_id={run.id}, "
                    f"total={result.get('total', 0)}, success={result.get('success', 0)}"
                )

        except Exception as e:
            logger.error(f"[{self.name}] Writing task 실행 실패: run_id={run.id}, error={e}", exc_info=True)
            try:
                schedule_service = TaskScheduleService(db)
                schedule_service.fail_run(run.id, str(e))
            except Exception:
                pass
        finally:
            self._update_worker_state("idle")
            db.close()

    def _run_writing_worker_sync(
        self,
        schedule: TaskSchedule,
        run: TaskScheduleRun
    ) -> dict:
        """WritingWorker 동기 실행 (별도 스레드에서 호출).

        Args:
            schedule: 스케줄
            run: 실행 기록

        Returns:
            실행 결과 dict
        """
        db = SessionLocal()
        try:
            worker = WritingWorker(db)
            return worker.run(schedule, run)
        except Exception as e:
            logger.error(f"[{self.name}] WritingWorker 실행 오류: {e}", exc_info=True)
            return {"error": str(e)}
        finally:
            db.close()

    # =====================================
    # Keyword Analysis 스케줄 처리
    # =====================================

    async def _process_keyword_analysis_schedule(
        self,
        db,
        schedule: TaskSchedule,
        schedule_service: TaskScheduleService
    ):
        """Keyword Analysis 스케줄 처리.

        Args:
            db: DB 세션
            schedule: 크롤링 스케줄
            schedule_service: 스케줄 서비스
        """
        try:
            config = schedule.get_target_config()

            # 수동 실행 요청 확인 (API에서 즉시 실행 버튼 클릭 시)
            manual_run = schedule_service.get_pending_manual_run(schedule.id)
            if manual_run:
                task_name = f"keyword_analysis_{schedule.id}_run_{manual_run.id}"
                if not self._is_task_running(task_name):
                    # worker_id 업데이트
                    manual_run.worker_id = self.name
                    db.commit()
                    self._create_task(
                        self._execute_keyword_analysis(manual_run, config),
                        task_name
                    )
                    logger.info(f"[{self.name}] 수동 Keyword Analysis 태스크 시작: run_id={manual_run.id}")
                return

            # cron 스케줄의 경우 should_run_now 체크를 위해 InstagramScheduler 사용
            # 시간 기반 실행 확인을 위한 간단한 체크
            min_interval = config.get("min_interval_hours", 168)  # 기본 7일 (168시간)

            # 마지막 실행 시간 조회
            last_run = schedule_service.get_latest_run(schedule.id)
            last_run_time = last_run.started_at if last_run else None

            # 간단한 간격 체크 (cron 대신)
            should_run = False
            if last_run_time is None:
                should_run = True
            else:
                hours_since = (datetime.now() - last_run_time).total_seconds() / 3600
                if hours_since >= min_interval:
                    should_run = True

            if should_run:
                logger.info(f"[{self.name}] Keyword Analysis 스케줄 실행 시간 도래: schedule_id={schedule.id}")

                # 이미 활성 실행이 있는지 확인
                if schedule_service.has_active_run(schedule.id):
                    logger.info(f"[{self.name}] 이미 활성 실행 존재, 스킵")
                    return

                # 실행 시작
                run = schedule_service.start_run(
                    schedule_id=schedule.id,
                    worker_id=self.name,
                    config_snapshot=config
                )

                task_name = f"keyword_analysis_{schedule.id}_run_{run.id}"
                if not self._is_task_running(task_name):
                    self._create_task(
                        self._execute_keyword_analysis(run, config),
                        task_name
                    )
                    logger.info(f"[{self.name}] Keyword Analysis 태스크 시작: run_id={run.id}")

        except Exception as e:
            logger.error(f"[{self.name}] Keyword Analysis 스케줄 처리 오류: schedule_id={schedule.id}, error={e}", exc_info=True)

    async def _execute_keyword_analysis(
        self,
        run: TaskScheduleRun,
        config: dict
    ):
        """Keyword Analysis 실행.

        Args:
            run: 실행 기록
            config: 분석 설정
        """
        db = SessionLocal()
        try:
            schedule_service = TaskScheduleService(db)

            self._update_worker_state("analyzing", "keywords")

            # KeywordAnalyzer 실행 (동기 호출을 별도 스레드에서 실행)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._run_keyword_analysis_sync,
                config
            )

            if result.get("error"):
                schedule_service.fail_run(run.id, result["error"])
                logger.error(f"[{self.name}] Keyword Analysis 실패: {result['error']}")
            else:
                # 결과 처리
                total_keywords = result.get("saved_keywords") or result.get("new_keywords", 0) + result.get("updated_keywords", 0)
                schedule_service.complete_run(
                    run.id,
                    collected_count=result.get("total_sources") or result.get("new_sources", 0),
                    saved_count=total_keywords,
                    stop_reason="completed"
                )
                schedule_service.update_schedule_after_run(run.schedule_id)
                logger.info(
                    f"[{self.name}] Keyword Analysis 완료: run_id={run.id}, "
                    f"keywords={total_keywords}"
                )

        except Exception as e:
            logger.error(f"[{self.name}] Keyword Analysis 실행 실패: run_id={run.id}, error={e}", exc_info=True)
            try:
                schedule_service = TaskScheduleService(db)
                schedule_service.fail_run(run.id, str(e))
            except Exception:
                pass
        finally:
            self._update_worker_state("idle")
            db.close()

    def _run_keyword_analysis_sync(self, config: dict) -> dict:
        """KeywordAnalyzer 동기 실행 (별도 스레드에서 호출).

        Args:
            config: 분석 설정

        Returns:
            실행 결과 dict
        """
        db = SessionLocal()
        try:
            from app.modules.writing.services.keyword_analyzer import KeywordAnalyzer

            analyzer = KeywordAnalyzer(db)

            mode = config.get("mode", "incremental")
            min_freq = config.get("min_freq", 3)
            min_length = config.get("min_length", 2)

            if mode == "full":
                result = analyzer.analyze_all(min_freq=min_freq, min_length=min_length)
            else:
                result = analyzer.analyze_incremental(min_freq=min_freq, min_length=min_length)

            return result
        except Exception as e:
            logger.error(f"[{self.name}] KeywordAnalyzer 실행 오류: {e}", exc_info=True)
            return {"error": str(e)}
        finally:
            db.close()

    # =====================================
    # Topic Extract 스케줄 처리
    # =====================================

    async def _process_topic_extract_schedule(
        self,
        db,
        schedule: TaskSchedule,
        schedule_service: TaskScheduleService
    ):
        """Topic Extract 스케줄 처리.

        Args:
            db: DB 세션
            schedule: 스케줄
            schedule_service: 스케줄 서비스
        """
        try:
            config = schedule.get_target_config()

            # 수동 실행 요청 확인
            manual_run = schedule_service.get_pending_manual_run(schedule.id)
            if manual_run:
                task_name = f"topic_extract_{schedule.id}_run_{manual_run.id}"
                if not self._is_task_running(task_name):
                    manual_run.worker_id = self.name
                    db.commit()
                    self._create_task(
                        self._execute_topic_extract(manual_run, config),
                        task_name
                    )
                    logger.info(f"[{self.name}] 수동 Topic Extract 태스크 시작: run_id={manual_run.id}")
                return

            # 간격 체크
            min_interval = config.get("min_interval_hours", 20)  # 기본 20시간

            # 마지막 실행 시간 조회
            last_run = schedule_service.get_latest_run(schedule.id)
            last_run_time = last_run.started_at if last_run else None

            should_run = False
            if last_run_time is None:
                should_run = True
            else:
                hours_since = (datetime.now() - last_run_time).total_seconds() / 3600
                if hours_since >= min_interval:
                    should_run = True

            if should_run:
                logger.info(f"[{self.name}] Topic Extract 스케줄 실행 시간 도래: schedule_id={schedule.id}")

                # 이미 활성 실행이 있는지 확인
                if schedule_service.has_active_run(schedule.id):
                    logger.info(f"[{self.name}] 이미 활성 실행 존재, 스킵")
                    return

                # 실행 시작
                run = schedule_service.start_run(
                    schedule_id=schedule.id,
                    worker_id=self.name,
                    config_snapshot=config
                )

                task_name = f"topic_extract_{schedule.id}_run_{run.id}"
                if not self._is_task_running(task_name):
                    self._create_task(
                        self._execute_topic_extract(run, config),
                        task_name
                    )
                    logger.info(f"[{self.name}] Topic Extract 태스크 시작: run_id={run.id}")

        except Exception as e:
            logger.error(f"[{self.name}] Topic Extract 스케줄 처리 오류: schedule_id={schedule.id}, error={e}", exc_info=True)

    async def _execute_topic_extract(
        self,
        run: TaskScheduleRun,
        config: dict
    ):
        """Topic Extract 실행.

        Args:
            run: 실행 기록
            config: 설정
        """
        db = SessionLocal()
        try:
            schedule_service = TaskScheduleService(db)
            schedule = db.query(TaskSchedule).filter_by(id=run.schedule_id).first()

            self._update_worker_state("extracting", "topics")

            # TopicExtractWorker 실행 (동기 호출을 별도 스레드에서 실행)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._run_topic_extract_sync,
                schedule,
                run
            )

            if result.get("error"):
                schedule_service.fail_run(run.id, result["error"])
                logger.error(f"[{self.name}] Topic Extract 실패: {result['error']}")
            else:
                schedule_service.complete_run(
                    run.id,
                    collected_count=result.get("total", 0),
                    saved_count=result.get("extracted", 0),
                    stop_reason="completed"
                )
                schedule_service.update_schedule_after_run(run.schedule_id)
                logger.info(
                    f"[{self.name}] Topic Extract 완료: run_id={run.id}, "
                    f"total={result.get('total', 0)}, extracted={result.get('extracted', 0)}"
                )

        except Exception as e:
            logger.error(f"[{self.name}] Topic Extract 실행 실패: run_id={run.id}, error={e}", exc_info=True)
            try:
                schedule_service = TaskScheduleService(db)
                schedule_service.fail_run(run.id, str(e))
            except Exception:
                pass
        finally:
            self._update_worker_state("idle")
            db.close()

    def _run_topic_extract_sync(
        self,
        schedule: TaskSchedule,
        run: TaskScheduleRun
    ) -> dict:
        """TopicExtractWorker 동기 실행 (별도 스레드에서 호출).

        Args:
            schedule: 스케줄
            run: 실행 기록

        Returns:
            실행 결과 dict
        """
        db = SessionLocal()
        try:
            worker = TopicExtractWorker(db)
            return worker.run(schedule, run)
        except Exception as e:
            logger.error(f"[{self.name}] TopicExtractWorker 실행 오류: {e}", exc_info=True)
            return {"error": str(e)}
        finally:
            db.close()

    # =====================================
    # Report 스케줄 처리
    # =====================================

    async def _process_report_schedule(
        self,
        db,
        schedule: TaskSchedule,
        schedule_service: TaskScheduleService
    ):
        """Report 스케줄 처리.

        Args:
            db: DB 세션
            schedule: 스케줄
            schedule_service: 스케줄 서비스
        """
        try:
            config = schedule.get_target_config()

            # 타임 윈도우 확인
            time_windows = parse_time_windows(config.get("time_windows", []))
            min_interval = config.get("min_interval_hours", 24)

            scheduler = InstagramScheduler(
                daily_runs=config.get("daily_runs", 1),
                time_windows=time_windows,
            )

            # 마지막 실행 시간 조회
            last_run = schedule_service.get_latest_run(schedule.id)
            last_run_time = last_run.started_at if last_run else None

            if scheduler.should_run_now(last_run=last_run_time, min_interval_hours=min_interval):
                logger.info(f"[{self.name}] Report 스케줄 실행 시간 도래: schedule_id={schedule.id}")

                # 이미 활성 실행이 있는지 확인
                if schedule_service.has_active_run(schedule.id):
                    logger.info(f"[{self.name}] 이미 활성 실행 존재, 스킵")
                    return

                # 실행 시작
                run = schedule_service.start_run(
                    schedule_id=schedule.id,
                    worker_id=self.name,
                    config_snapshot=config
                )

                task_name = f"report_{schedule.id}_run_{run.id}"
                if not self._is_task_running(task_name):
                    self._create_task(
                        self._execute_report_generation(schedule, run, config),
                        task_name
                    )
                    logger.info(f"[{self.name}] Report 생성 태스크 시작: run_id={run.id}")

        except Exception as e:
            logger.error(f"[{self.name}] Report 스케줄 처리 오류: schedule_id={schedule.id}, error={e}", exc_info=True)

    async def _execute_report_generation(
        self,
        schedule: TaskSchedule,
        run: TaskScheduleRun,
        config: dict
    ):
        """보고서 생성 실행.

        Args:
            schedule: 스케줄
            run: 실행 기록
            config: 보고서 설정
        """
        from datetime import timedelta

        db = SessionLocal()
        try:
            schedule_service = TaskScheduleService(db)

            self._update_worker_state("generating", f"report_{schedule.id}")

            from app.modules.reports.services.report_service import ReportService
            report_service = ReportService(db)

            # 기간 계산
            period = config.get("period", "daily")
            period_end = datetime.now()
            if period == "daily":
                period_start = period_end - timedelta(days=1)
            elif period == "weekly":
                period_start = period_end - timedelta(weeks=1)
            else:
                period_start = period_end - timedelta(days=30)

            # LLM 요청 생성
            llm_request = report_service.request_report(
                report_type=config.get("report_type", "daily_summary"),
                period_start=period_start,
                period_end=period_end,
                config=config
            )

            # 완료 처리 (LLM Worker가 비동기로 처리)
            schedule_service.complete_run(
                run.id,
                collected_count=1,
                saved_count=1,
                stop_reason=f"report_requested_id_{llm_request.id}"
            )
            schedule_service.update_schedule_after_run(run.schedule_id)
            logger.info(
                f"[{self.name}] Report 요청 완료: run_id={run.id}, "
                f"llm_request_id={llm_request.id}"
            )

        except Exception as e:
            logger.error(f"[{self.name}] Report 생성 실행 실패: run_id={run.id}, error={e}", exc_info=True)
            try:
                schedule_service = TaskScheduleService(db)
                schedule_service.fail_run(run.id, str(e))
            except Exception:
                pass
        finally:
            self._update_worker_state("idle")
            db.close()

    # ========== pytest_run 스케줄 ==========

    @staticmethod
    def _should_run_cron(schedule: TaskSchedule, last_run_at: Optional[datetime]) -> bool:
        """cron/time_window 스케줄이 지금 실행될 시간인지 판단.

        playwright 미의존 유틸 `should_run_cron_now`에 위임.
        """
        from app.services.pytest_runner_service import should_run_cron_now
        return should_run_cron_now(schedule.schedule_value or "", last_run_at)

    async def _process_pytest_schedule(
        self,
        db,
        schedule: TaskSchedule,
        schedule_service: TaskScheduleService
    ):
        """pytest_run 스케줄 처리."""
        try:
            last_run = schedule_service.get_latest_run(schedule.id)
            last_run_at = last_run.started_at if last_run else None

            if not self._should_run_cron(schedule, last_run_at):
                return

            logger.info(f"[{self.name}] pytest_run 실행 시간 도래: schedule_id={schedule.id}")

            if schedule_service.has_active_run(schedule.id):
                logger.info(f"[{self.name}] 이미 활성 실행 존재, 스킵")
                return

            config = schedule.get_target_config()
            run = schedule_service.start_run(
                schedule_id=schedule.id,
                worker_id=self.name,
                config_snapshot=config
            )

            task_name = f"pytest_run_{schedule.id}_run_{run.id}"
            if not self._is_task_running(task_name):
                self._create_task(
                    self._execute_pytest_run(schedule, run, config),
                    task_name
                )
                logger.info(f"[{self.name}] pytest 실행 태스크 시작: run_id={run.id}")

        except Exception as e:
            logger.error(
                f"[{self.name}] pytest_run 스케줄 처리 오류: schedule_id={schedule.id}, error={e}",
                exc_info=True
            )

    async def _execute_pytest_run(
        self,
        schedule: TaskSchedule,
        run: TaskScheduleRun,
        config: dict
    ):
        """pytest 실행 + 결과 저장 + LLM 수정계획 요청 생성."""
        import asyncio as _asyncio
        from app.services.pytest_runner_service import PytestRunnerService

        db = SessionLocal()
        try:
            schedule_service = TaskScheduleService(db)
            self._update_worker_state("running_pytest", f"pytest_{schedule.id}")

            test_path = config.get("test_path", "tests/")
            extra_args_raw = config.get("extra_args", [])
            extra_args = extra_args_raw if isinstance(extra_args_raw, list) else []
            timeout = config.get("timeout", 1800)

            runner = PytestRunnerService(db)
            loop = _asyncio.get_event_loop()

            test_run = await loop.run_in_executor(
                None,
                lambda: runner.run_tests(
                    test_path=test_path,
                    extra_args=extra_args,
                    timeout=timeout,
                    triggered_by="scheduler",
                    schedule_run_id=run.id,
                )
            )

            if config.get("auto_fix_plan", True) and (test_run.failed + test_run.errors) > 0:
                provider = config.get("provider", "claude")
                model = config.get("model", "")
                await loop.run_in_executor(
                    None,
                    lambda: runner.create_fix_plan_requests(
                        test_run_id=test_run.id,
                        provider=provider,
                        model=model,
                    )
                )

            schedule_service.complete_run(
                run.id,
                collected_count=test_run.total_tests,
                saved_count=test_run.failed + test_run.errors,
                stop_reason=f"pytest_run_id_{test_run.id}"
            )
            schedule_service.update_schedule_after_run(run.schedule_id)
            logger.info(
                f"[{self.name}] pytest 완료: run_id={run.id}, "
                f"total={test_run.total_tests}, failed={test_run.failed}"
            )

        except Exception as e:
            logger.error(
                f"[{self.name}] pytest 실행 실패: run_id={run.id}, error={e}",
                exc_info=True
            )
            try:
                TaskScheduleService(db).fail_run(run.id, str(e))
            except Exception:
                pass
        finally:
            self._update_worker_state("idle")
            db.close()

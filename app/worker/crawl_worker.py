"""
통합 크롤링 워커 프로세스

API 서버와 분리되어 독립적으로 크롤링 작업을 수행합니다.
Instagram 크롤링과 Universal URL 크롤링을 모두 처리합니다.

실행 방법:
    python -m app.worker.crawl_worker

주요 기능:
    - Instagram Pending 크롤링 요청 처리 (InstagramCrawlRequest)
    - Universal Pending 크롤링 요청 처리 (UniversalCrawlRequest)
    - Instagram 스케줄 기반 자동 크롤링 실행 (InstagramScheduler)
    - 로그인 상태 확인 및 실패 처리

삭제 예정 파일:
    - app/worker/instagram_worker.py (이 파일로 대체, 안정화 후 삭제)
"""
import asyncio
import sys
import os
import signal
import logging
import subprocess
import shutil
from datetime import datetime
from pathlib import Path

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 비동기 로거 설정
from app.utils.async_logger import AsyncLoggerManager

# 워커 전용 비동기 로거 설정
logger = AsyncLoggerManager.setup_worker_logger(
    log_prefix="crawl_worker",
    log_dir=Path("logs"),
    level=logging.DEBUG
)
logger.info(f"통합 크롤링 워커 비동기 로거 초기화 완료 - 로그 파일: {logger.log_file}")

# 모듈 import
try:
    logger.info("모듈 import 시작...")

    from app.config import settings
    logger.debug("app.config import 완료")

    from app.database import SessionLocal
    logger.debug("app.database import 완료")

    from app.models import Account, InstagramCrawlRequest, InstagramCrawlRun, InstagramScheduleConfig
    from app.models.universal_crawl import UniversalCrawlRequest, CrawledPage
    logger.debug("app.models import 완료")

    from app.modules.instagram.services.request_service import CrawlRequestService
    from app.modules.instagram.services.crawl_service import CrawlService
    from app.modules.instagram.services.scheduler import InstagramScheduler
    from app.modules.instagram.services.crawler import InstagramCrawler, CrawlOptions
    from app.modules.instagram.services.worker_status_service import WorkerStatusService
    from app.modules.instagram.models.schemas import TimeWindow
    logger.debug("instagram services import 완료")

    from app.services.universal_crawl_service import universal_crawl_service
    from app.services.page_extractor.factory import get_extractor_factory
    logger.debug("universal crawl services import 완료")

    from app.shared.browser.context_manager import ContextManager
    from app.shared.browser.tab_pool_manager import TabPoolManager
    logger.debug("browser_service import 완료")

    # 크롤러 관련 로거들이 워커 로거와 같은 핸들러를 사용하도록 설정
    worker_handlers = logger.handlers
    for logger_name in ['instagram.crawler', 'instagram.crawl_service', 'instagram.post_service', 'universal_crawl']:
        sub_logger = logging.getLogger(logger_name)
        sub_logger.setLevel(logging.DEBUG)
        for handler in worker_handlers:
            sub_logger.addHandler(handler)
        sub_logger.propagate = False  # 중복 로깅 방지
    logger.debug("서브 로거 설정 완료")

    logger.info("모든 모듈 import 완료")

except Exception as e:
    import traceback
    logger.critical(f"모듈 import 중 치명적 오류: {e}")
    logger.critical(f"Traceback:\n{traceback.format_exc()}")
    AsyncLoggerManager.shutdown()
    sys.exit(1)


class CrawlWorker:
    """통합 크롤링 워커 (Instagram + Universal)."""

    # 브라우저 closed 에러 키워드들
    BROWSER_CLOSED_KEYWORDS = [
        "Target page, context or browser has been closed",
        "browser has been closed",
        "context has been closed",
        "page has been closed",
        "Target closed",
    ]

    def __init__(self):
        self.shutdown_event = asyncio.Event()
        self.continue_event = asyncio.Event()  # 크롤링 완료 시 즉시 깨우기용
        self.context_manager: ContextManager = None
        self.tab_pool_manager: TabPoolManager = None
        self.check_interval = 30  # 30초마다 체크
        self.pid = os.getpid()
        self.start_time: datetime = None
        self.worker_id: str = None  # 워커 상태 추적용

        # 백그라운드 태스크 관리 (병렬 크롤링용)
        self._running_tasks: set = set()

        # ExtractorFactory 인스턴스
        self._extractor_factory = get_extractor_factory()

    async def start(self):
        """워커 시작."""
        logger.info(f"통합 크롤링 워커 시작 (PID: {self.pid})")
        self.start_time = datetime.now()

        # 워커 상태 등록
        self._register_worker_status()

        try:
            await self._initialize()
            await self._main_loop()
        finally:
            await self._cleanup()

    def _register_worker_status(self):
        """워커 상태를 DB에 등록합니다."""
        db = SessionLocal()
        try:
            service = WorkerStatusService(db)
            status = service.register_worker()
            self.worker_id = status.worker_id
            logger.info(f"워커 상태 등록 완료: worker_id={self.worker_id}")
        except Exception as e:
            logger.error(f"워커 상태 등록 실패: {e}")
        finally:
            db.close()

    def _update_heartbeat(self):
        """워커 heartbeat를 업데이트합니다."""
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = WorkerStatusService(db)
            service.update_heartbeat(self.worker_id)
        except Exception as e:
            logger.warning(f"Heartbeat 업데이트 실패: {e}")
        finally:
            db.close()

    def _update_worker_state(self, state: str, account: str = None, run_id: int = None):
        """워커 상태를 업데이트합니다."""
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = WorkerStatusService(db)
            service.update_state(self.worker_id, state, account, run_id)
        except Exception as e:
            logger.warning(f"워커 상태 업데이트 실패: {e}")
        finally:
            db.close()

    def _mark_worker_dead(self):
        """워커를 종료 상태로 표시합니다."""
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = WorkerStatusService(db)
            service.mark_dead(self.worker_id)
            logger.info(f"워커 종료 상태 표시 완료: worker_id={self.worker_id}")
        except Exception as e:
            logger.error(f"워커 종료 상태 표시 실패: {e}")
        finally:
            db.close()

    async def stop(self):
        """워커 종료."""
        logger.info("통합 크롤링 워커 종료 요청")
        self.shutdown_event.set()

    async def _initialize(self):
        """초기화."""
        logger.info("통합 크롤링 워커 초기화 시작")

        # 오래된 processing 요청 정리 (좀비 요청 방지)
        self._cleanup_stale_requests()

        # 기존 브라우저 프로필 Lock 정리 (비정상 종료 후 재시작 시)
        self._cleanup_stale_browser_locks()

        # 브라우저 컨텍스트 매니저는 크롤링 시 lazy 초기화
        self.context_manager = None

        logger.info("통합 크롤링 워커 초기화 완료")

    def _cleanup_stale_browser_locks(self):
        """비정상 종료된 브라우저의 Lock 파일 및 프로세스 정리."""
        from app.config import settings

        profile_base = Path(settings.DATA_DIR) / settings.BROWSER_PROFILES_DIR

        if not profile_base.exists():
            return

        try:
            # 1. 해당 프로필을 사용하는 모든 Chromium 프로세스 종료
            killed_count = self._kill_chromium_for_profiles(profile_base)
            if killed_count > 0:
                logger.info(f"기존 Chromium 프로세스 {killed_count}개 종료됨")
                import time
                time.sleep(1)

            # 2. Lock 파일 정리
            for profile_dir in profile_base.iterdir():
                if not profile_dir.is_dir():
                    continue
                self._remove_lock_files(profile_dir)

        except Exception as e:
            logger.warning(f"브라우저 정리 중 오류 (무시): {e}")

    def _kill_chromium_for_profiles(self, profile_base: Path) -> int:
        """프로필 디렉토리를 사용하는 Chromium 프로세스 종료."""
        killed_count = 0

        try:
            if sys.platform == "win32":
                result = subprocess.run(
                    ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/FO", "CSV", "/V"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'chrome.exe' in line.lower():
                            try:
                                parts = line.split(',')
                                if len(parts) > 1:
                                    pid_str = parts[1].strip('"')
                                    if pid_str.isdigit():
                                        pid = int(pid_str)
                                        if self._is_chromium_using_profile(pid, profile_base):
                                            logger.info(f"Chromium 프로세스 종료: PID {pid}")
                                            subprocess.run(
                                                ["taskkill", "/F", "/PID", str(pid)],
                                                capture_output=True,
                                                timeout=5
                                            )
                                            killed_count += 1
                            except (ValueError, IndexError):
                                continue
            else:
                subprocess.run(
                    ["pkill", "-f", str(profile_base)],
                    capture_output=True,
                    timeout=5
                )
                killed_count = 1

        except subprocess.TimeoutExpired:
            logger.warning("Chromium 종료 타임아웃")
        except Exception as e:
            logger.warning(f"Chromium 종료 오류: {e}")

        return killed_count

    def _is_chromium_using_profile(self, pid: int, profile_base: Path) -> bool:
        """특정 PID의 Chromium이 해당 프로필 경로를 사용하는지 확인."""
        try:
            if sys.platform == "win32":
                result = subprocess.run(
                    ["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    cmd_line = result.stdout.lower()
                    return 'browser_profiles' in cmd_line or 'ms-playwright' in cmd_line
            else:
                result = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "command="],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    return str(profile_base) in result.stdout
        except Exception:
            pass

        return False

    def _remove_lock_files(self, profile_dir: Path):
        """프로필 디렉토리의 Lock 파일들 제거."""
        lock_files = ["SingletonLock", "SingletonSocket", "SingletonCookie"]

        for lock_name in lock_files:
            lock_path = profile_dir / lock_name
            if lock_path.exists():
                try:
                    if lock_path.is_file() or lock_path.is_symlink():
                        lock_path.unlink()
                    else:
                        shutil.rmtree(lock_path, ignore_errors=True)
                    logger.debug(f"Lock 파일 삭제: {lock_path}")
                except Exception as e:
                    logger.warning(f"Lock 파일 삭제 실패 ({lock_path}): {e}")

    def _cleanup_stale_requests(self):
        """오래된 processing 상태 요청 정리."""
        db = SessionLocal()
        try:
            # Instagram 요청 정리
            request_service = CrawlRequestService(db)
            cleaned = request_service.cleanup_stale_processing_requests(timeout_minutes=30)
            if cleaned > 0:
                logger.info(f"Instagram: {cleaned}개의 오래된 processing 요청 정리 완료")

            # Universal 요청 정리
            from datetime import timedelta
            cutoff = datetime.now() - timedelta(minutes=30)
            stale_universal = db.query(UniversalCrawlRequest).filter(
                UniversalCrawlRequest.status == "processing",
                UniversalCrawlRequest.started_at < cutoff
            ).all()

            for req in stale_universal:
                req.status = "failed"
                req.error_message = "워커 재시작으로 인한 타임아웃"
                req.completed_at = datetime.now()

            if stale_universal:
                db.commit()
                logger.info(f"Universal: {len(stale_universal)}개의 오래된 processing 요청 정리 완료")

        except Exception as e:
            logger.error(f"Stale request 정리 오류: {e}")
        finally:
            db.close()

    async def _cleanup(self):
        """워커 종료 시 정리."""
        logger.info("통합 크롤링 워커 정리 시작")

        # 1. 실행 중인 태스크 취소
        if self._running_tasks:
            logger.info(f"실행 중인 태스크 {len(self._running_tasks)}개 취소 중...")
            for task in self._running_tasks:
                if not task.done():
                    task.cancel()

            try:
                await asyncio.gather(*self._running_tasks, return_exceptions=True)
            except Exception as e:
                logger.warning(f"태스크 대기 중 오류 (무시): {e}")

            self._running_tasks.clear()

        # 2. 워커 상태를 종료로 표시
        self._mark_worker_dead()

        # 3. 탭 풀 정리
        if self.tab_pool_manager:
            try:
                await self.tab_pool_manager.close_all_tabs()
                logger.info("탭 풀 정리 완료")
            except Exception as e:
                logger.error(f"탭 풀 정리 오류: {e}")

        # 4. 브라우저 컨텍스트 정리
        if self.context_manager:
            try:
                await self.context_manager.close_all_contexts()
                logger.info("브라우저 컨텍스트 정리 완료")
            except Exception as e:
                logger.error(f"브라우저 컨텍스트 정리 오류: {e}")

        logger.info("통합 크롤링 워커 정리 완료")
        AsyncLoggerManager.shutdown()

    async def _main_loop(self):
        """메인 루프 (비블로킹 방식)."""
        logger.info(f"메인 루프 시작 (비블로킹 모드, 체크 간격: 1초)")

        while not self.shutdown_event.is_set():
            try:
                # Heartbeat 업데이트
                self._update_heartbeat()

                # 완료된 태스크 정리
                self._cleanup_completed_tasks()

                # 1. Instagram Pending 요청 디스패치 (백그라운드)
                await self._dispatch_instagram_pending_requests()

                # 2. Universal Pending 요청 디스패치 (백그라운드)
                await self._dispatch_universal_pending_requests()

                # 3. Instagram 스케줄 기반 실행 디스패치 (백그라운드)
                await self._dispatch_scheduled_runs()

                # 4. 짧은 대기 (새 요청 빠르게 체크)
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                logger.info("메인 루프 취소됨")
                break
            except Exception as e:
                logger.error(f"메인 루프 오류: {e}", exc_info=True)
                await asyncio.sleep(5)

    def _cleanup_completed_tasks(self):
        """완료된 백그라운드 태스크 정리."""
        completed = {t for t in self._running_tasks if t.done()}
        for task in completed:
            try:
                exc = task.exception()
                if exc:
                    logger.error(f"태스크 예외: {task.get_name()} - {exc}")
            except asyncio.CancelledError:
                pass
            except asyncio.InvalidStateError:
                pass
        self._running_tasks -= completed

    def _is_request_running(self, request_id: int, prefix: str = "crawl") -> bool:
        """요청이 이미 실행 중인지 확인."""
        task_name = f"{prefix}_{request_id}"
        for task in self._running_tasks:
            if task.get_name() == task_name:
                return True
        return False

    # ========== Instagram 크롤링 관련 ==========

    async def _dispatch_instagram_pending_requests(self):
        """Instagram Pending 요청을 백그라운드 태스크로 디스패치."""
        db = SessionLocal()
        try:
            request_service = CrawlRequestService(db)

            pending_list = request_service.get_pending_requests(limit=5) if hasattr(request_service, 'get_pending_requests') else []

            if not pending_list:
                pending = request_service.get_pending_request()
                if pending:
                    pending_list = [pending]

            for pending in pending_list:
                if self._is_request_running(pending.id, "ig"):
                    continue

                task = asyncio.create_task(
                    self._execute_instagram_crawl_safe(pending),
                    name=f"ig_{pending.id}"
                )
                self._running_tasks.add(task)
                logger.info(f"Instagram 크롤링 태스크 시작: request_id={pending.id}, type={getattr(pending, 'request_type', 'feed')}")

        except Exception as e:
            logger.error(f"Instagram Pending 요청 디스패치 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _dispatch_scheduled_runs(self):
        """Instagram 스케줄 기반 실행을 백그라운드로 디스패치."""
        db = SessionLocal()
        try:
            crawl_service = CrawlService(db)
            config = crawl_service.get_schedule_config()

            if not config or not config.enabled:
                return

            if not config.service_account_id:
                return

            time_windows = [
                TimeWindow(**tw) for tw in (config.time_windows or [])
            ]
            scheduler = InstagramScheduler(
                daily_runs=config.daily_runs,
                time_windows=time_windows,
            )

            last_run = crawl_service.get_last_run(service_account_id=config.service_account_id)
            last_run_time = last_run.started_at if last_run else None

            min_interval = getattr(config, 'min_interval_hours', 2) or 2
            if scheduler.should_run_now(
                last_run=last_run_time,
                min_interval_hours=min_interval,
            ):
                logger.info(f"스케줄 실행 시간 도래: service_account_id={config.service_account_id}")

                request_service = CrawlRequestService(db)
                if request_service.has_active_request(config.service_account_id):
                    logger.info("이미 활성 요청 존재, 스킵")
                    return

                request = request_service.create_request(
                    service_account_id=config.service_account_id,
                    requested_by="scheduler",
                )

                if not self._is_request_running(request.id, "ig"):
                    task = asyncio.create_task(
                        self._execute_instagram_crawl_safe(request),
                        name=f"ig_{request.id}"
                    )
                    self._running_tasks.add(task)
                    logger.info(f"스케줄 Instagram 크롤링 태스크 시작: request_id={request.id}")

        except Exception as e:
            logger.error(f"스케줄 디스패치 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _execute_instagram_crawl_safe(self, request: InstagramCrawlRequest):
        """안전한 Instagram 크롤링 실행."""
        db = SessionLocal()
        try:
            request_service = CrawlRequestService(db)
            crawl_service = CrawlService(db)

            request_service.mark_processing(request.id)

            request_type = getattr(request, 'request_type', 'feed') or 'feed'
            logger.info(f"Instagram 크롤링 시작: request_id={request.id}, type={request_type}")

            if request_type == "single_post":
                await self._execute_instagram_single_post_recrawl(request, db, request_service, crawl_service)
            elif request_type == "single_post_url":
                await self._execute_instagram_url_crawl(request, db, request_service, crawl_service)
            else:
                await self._execute_instagram_feed_crawl(request, db, request_service, crawl_service)

        except Exception as e:
            logger.error(f"Instagram 크롤링 실패: request_id={request.id}, error={e}", exc_info=True)
            try:
                request_service = CrawlRequestService(db)
                request_service.mark_failed(request.id, str(e))
            except Exception:
                pass
        finally:
            db.close()

    async def _get_tab_for_request(self, request_id: int, service_account_id: int = None):
        """TabPoolManager를 통해 탭 획득."""
        if self.context_manager is None:
            logger.info("ContextManager 초기화")
            self.context_manager = ContextManager()

        if self.tab_pool_manager is None:
            logger.info("TabPoolManager 초기화")
            self.tab_pool_manager = TabPoolManager(self.context_manager)

        tab = await self.tab_pool_manager.get_tab(
            target_id=request_id,
            service_account_id=service_account_id
        )
        logger.info(f"탭 획득 완료: request_id={request_id}, service_account_id={service_account_id}")
        return tab

    async def _release_tab(self, tab):
        """사용 완료된 탭 반환."""
        if self.tab_pool_manager and tab:
            await self.tab_pool_manager.release_tab(tab)

    async def _get_page_for_account(self, service_account_id: int = None):
        """계정별 브라우저 페이지 가져오기."""
        if self.context_manager is None:
            logger.info("ContextManager 초기화")
            self.context_manager = ContextManager()

        context = await self.context_manager.get_or_create_context(service_account_id)

        pages = context.pages
        page = None

        if pages:
            for p in pages:
                try:
                    if not p.is_closed():
                        page = p
                        break
                except Exception:
                    continue

        if page is None:
            page = await context.new_page()

        return page

    async def _check_instagram_login(self, page) -> bool:
        """Instagram 로그인 상태 확인."""
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
            logger.warning(f"Instagram 로그인 상태 확인 실패: {e}")
            return False

    def _is_browser_closed_error(self, error: Exception) -> bool:
        """브라우저 closed 에러인지 확인."""
        error_msg = str(error).lower()
        return any(keyword.lower() in error_msg for keyword in self.BROWSER_CLOSED_KEYWORDS)

    async def _recreate_browser_context(self, service_account_id: int = None):
        """브라우저 컨텍스트 재생성."""
        logger.info(f"브라우저 컨텍스트 재생성 시작 (service_account_id={service_account_id})")

        if self.context_manager:
            try:
                await self.context_manager.close_context(service_account_id)
                logger.info(f"기존 컨텍스트 닫기 완료 (service_account_id={service_account_id})")
            except Exception as e:
                logger.warning(f"기존 컨텍스트 닫기 실패 (무시): {e}")

            try:
                await self.context_manager.close_all_contexts()
                self.context_manager = None
                logger.info("ContextManager 초기화 완료")
            except Exception as e:
                logger.warning(f"ContextManager 초기화 실패 (무시): {e}")
                self.context_manager = None

        from app.config import settings
        profile_base = Path(settings.DATA_DIR) / settings.BROWSER_PROFILES_DIR
        killed = self._kill_chromium_for_profiles(profile_base)
        if killed > 0:
            logger.info(f"잔여 Chromium 프로세스 {killed}개 종료")

        for profile_dir in profile_base.iterdir():
            if profile_dir.is_dir():
                self._remove_lock_files(profile_dir)

        await asyncio.sleep(3)

        logger.info(f"브라우저 컨텍스트 재생성 준비 완료 (service_account_id={service_account_id})")

    async def _execute_instagram_feed_crawl(self, request: InstagramCrawlRequest, db, request_service, crawl_service):
        """Instagram 피드 크롤링 실행."""
        max_retries = 3
        retry_count = 0
        tab = None

        while retry_count <= max_retries:
            try:
                account = db.query(Account).filter(Account.id == request.service_account_id).first()
                if not account:
                    request_service.mark_failed(request.id, "계정을 찾을 수 없음")
                    logger.warning(f"계정 없음: service_account_id={request.service_account_id}")
                    return

                self._update_worker_state("crawling", account.name)

                tab = await self._get_tab_for_request(request.id, account.id)

                logger.info("인스타그램 피드 페이지로 이동 중...")
                await tab.goto("https://www.instagram.com/", wait_until="domcontentloaded")
                await tab.wait_for_timeout(2000)
                logger.info(f"인스타그램 페이지 로드 완료: {tab.url}")

                is_logged_in = await self._check_instagram_login(tab)
                if not is_logged_in:
                    account.is_logged_in = False
                    db.commit()
                    request_service.mark_failed(request.id, "Instagram 로그인 필요")
                    logger.warning(f"Instagram 로그인 필요: account={account.name}")
                    return
                else:
                    account.is_logged_in = True
                    db.commit()

                crawler = InstagramCrawler(tab)
                logger.info("InstagramCrawler 생성 완료, 크롤링 시작...")

                crawl_run = await crawl_service.run_crawl(
                    crawler=crawler,
                    service_account_id=request.service_account_id,
                )

                self._update_worker_state("crawling", account.name, crawl_run.id)

                logger.info(f"크롤링 완료: success={crawl_run.success}, collected={crawl_run.total_collected}, new={crawl_run.new_saved}")

                if crawl_run.success:
                    request_service.mark_completed(request.id, crawl_run.id)
                    logger.info(
                        f"크롤링 완료: request_id={request.id}, "
                        f"collected={crawl_run.total_collected}, new={crawl_run.new_saved}"
                    )
                else:
                    request_service.mark_failed(request.id, crawl_run.error_message or "크롤링 실패")
                    logger.warning(f"크롤링 실패: {crawl_run.error_message}")

                return

            except Exception as e:
                if self._is_browser_closed_error(e) and retry_count < max_retries:
                    retry_count += 1
                    logger.warning(f"브라우저 closed 에러 감지, 재시도 ({retry_count}/{max_retries}): {e}")
                    if tab:
                        await self._release_tab(tab)
                        tab = None
                    await self._recreate_browser_context(request.service_account_id)
                    continue

                request_service.mark_failed(request.id, str(e))
                logger.error(f"크롤링 예외: {e}", exc_info=True)
                return
            finally:
                if tab:
                    await self._release_tab(tab)
                self._update_worker_state("idle")

    async def _execute_instagram_single_post_recrawl(self, request: InstagramCrawlRequest, db, request_service, crawl_service):
        """Instagram 개별 게시물 재크롤링 실행."""
        max_retries = 3
        retry_count = 0
        tab = None

        while retry_count <= max_retries:
            try:
                target_post_id = getattr(request, 'target_post_id', None)
                if not target_post_id:
                    request_service.mark_failed(request.id, "대상 게시물 ID 없음")
                    logger.warning(f"대상 게시물 ID 없음: request_id={request.id}")
                    return

                account = db.query(Account).filter(Account.id == request.service_account_id).first()
                if not account:
                    request_service.mark_failed(request.id, "계정을 찾을 수 없음")
                    logger.warning(f"계정 없음: service_account_id={request.service_account_id}")
                    return

                self._update_worker_state("recrawling", account.name)

                tab = await self._get_tab_for_request(request.id, account.id)

                await tab.goto("https://www.instagram.com/", wait_until="domcontentloaded")
                await tab.wait_for_timeout(1000)
                is_logged_in = await self._check_instagram_login(tab)
                if not is_logged_in:
                    account.is_logged_in = False
                    db.commit()
                    request_service.mark_failed(request.id, "Instagram 로그인 필요")
                    logger.warning(f"Instagram 로그인 필요: account={account.name}")
                    return
                else:
                    account.is_logged_in = True
                    db.commit()

                crawler = InstagramCrawler(tab)
                logger.info(f"개별 게시물 재크롤링 시작: post_id={target_post_id}")

                result = await crawl_service.recrawl_single_post(
                    crawler=crawler,
                    post_id=target_post_id,
                )

                if result["success"]:
                    request.status = "completed"
                    request.processed_at = datetime.now()
                    db.commit()
                    logger.info(f"재크롤링 완료: request_id={request.id}, post_id={target_post_id}")
                else:
                    request_service.mark_failed(request.id, result["message"])
                    logger.warning(f"재크롤링 실패: {result['message']}")

                return

            except Exception as e:
                if self._is_browser_closed_error(e) and retry_count < max_retries:
                    retry_count += 1
                    logger.warning(f"브라우저 closed 에러 감지, 재시도 ({retry_count}/{max_retries}): {e}")
                    if tab:
                        await self._release_tab(tab)
                        tab = None
                    await self._recreate_browser_context(request.service_account_id)
                    continue

                request_service.mark_failed(request.id, str(e))
                logger.error(f"재크롤링 예외: {e}", exc_info=True)
                return
            finally:
                if tab:
                    await self._release_tab(tab)
                self._update_worker_state("idle")

    async def _execute_instagram_url_crawl(self, request: InstagramCrawlRequest, db, request_service, crawl_service):
        """Instagram URL로 단일 게시물 수집 실행."""
        max_retries = 3
        retry_count = 0
        tab = None

        while retry_count <= max_retries:
            try:
                target_url = getattr(request, 'target_url', None)
                if not target_url:
                    request_service.mark_failed(request.id, "대상 URL 없음")
                    logger.warning(f"대상 URL 없음: request_id={request.id}")
                    return

                account = db.query(Account).filter(Account.id == request.service_account_id).first()
                if not account:
                    request_service.mark_failed(request.id, "계정을 찾을 수 없음")
                    logger.warning(f"계정 없음: service_account_id={request.service_account_id}")
                    return

                self._update_worker_state("crawling", account.name)

                tab = await self._get_tab_for_request(request.id, account.id)

                await tab.goto("https://www.instagram.com/", wait_until="domcontentloaded")
                await tab.wait_for_timeout(1000)
                is_logged_in = await self._check_instagram_login(tab)
                if not is_logged_in:
                    account.is_logged_in = False
                    db.commit()
                    request_service.mark_failed(request.id, "Instagram 로그인 필요")
                    logger.warning(f"Instagram 로그인 필요: account={account.name}")
                    return
                else:
                    account.is_logged_in = True
                    db.commit()

                crawler = InstagramCrawler(tab)
                logger.info(f"URL 크롤링 시작: url={target_url}")

                result = await crawl_service.crawl_by_url(
                    crawler=crawler,
                    url=target_url,
                    service_account_id=request.service_account_id,
                )

                if result["success"]:
                    request.status = "completed"
                    request.processed_at = datetime.now()
                    db.commit()

                    is_new = result.get("is_new", False)
                    post = result.get("post")
                    post_id = post.id if post else None
                    logger.info(
                        f"URL 크롤링 완료: request_id={request.id}, "
                        f"post_id={post_id}, is_new={is_new}"
                    )
                else:
                    request_service.mark_failed(request.id, result["message"])
                    logger.warning(f"URL 크롤링 실패: {result['message']}")

                return

            except Exception as e:
                if self._is_browser_closed_error(e) and retry_count < max_retries:
                    retry_count += 1
                    logger.warning(f"브라우저 closed 에러 감지, 재시도 ({retry_count}/{max_retries}): {e}")
                    if tab:
                        await self._release_tab(tab)
                        tab = None
                    await self._recreate_browser_context(request.service_account_id)
                    continue

                request_service.mark_failed(request.id, str(e))
                logger.error(f"URL 크롤링 예외: {e}", exc_info=True)
                return
            finally:
                if tab:
                    await self._release_tab(tab)
                self._update_worker_state("idle")

    # ========== Universal 크롤링 관련 ==========

    async def _dispatch_universal_pending_requests(self):
        """Universal Pending 요청을 백그라운드 태스크로 디스패치."""
        db = SessionLocal()
        try:
            pending_list = universal_crawl_service.get_pending_requests(db, limit=5)

            for pending in pending_list:
                if self._is_request_running(pending.id, "uni"):
                    continue

                task = asyncio.create_task(
                    self._execute_universal_crawl_safe(pending.id),
                    name=f"uni_{pending.id}"
                )
                self._running_tasks.add(task)
                logger.info(f"Universal 크롤링 태스크 시작: request_id={pending.id}, url_type={pending.url_type}")

        except Exception as e:
            logger.error(f"Universal Pending 요청 디스패치 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _execute_universal_crawl_safe(self, request_id: int):
        """안전한 Universal 크롤링 실행."""
        db = SessionLocal()
        page = None
        try:
            request = universal_crawl_service.get_request(db, request_id)
            if not request:
                logger.warning(f"Universal 요청 없음: request_id={request_id}")
                return

            # processing 상태로 변경
            universal_crawl_service.mark_processing(db, request_id)
            self._update_worker_state("universal_crawling")

            logger.info(f"Universal 크롤링 시작: request_id={request_id}, url={request.url}")

            # 브라우저 페이지 획득
            page = await self._get_page_for_account(request.service_account_id)

            # 페이지 로드
            await page.goto(request.url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)  # 동적 콘텐츠 로딩 대기

            # 추출기 선택 및 추출 실행
            extractor = self._extractor_factory.get_extractor(request.url)
            logger.info(f"추출기 선택: {extractor.__class__.__name__}")

            extracted = await extractor.extract(page, request.url)

            if not extracted.success:
                universal_crawl_service.mark_failed(db, request_id, extracted.error or "추출 실패")
                logger.warning(f"Universal 크롤링 추출 실패: {extracted.error}")
                return

            # 결과 저장
            crawled_page = universal_crawl_service.create_crawled_page(
                db=db,
                url=request.url,
                url_type=request.url_type,
                title=extracted.title,
                description=extracted.description,
                content=extracted.content,
                extracted_data=extracted.structured_data,
                og_title=extracted.metadata.get("title"),
                og_description=extracted.metadata.get("description"),
                og_image=extracted.metadata.get("image"),
                extractor_used=extractor.__class__.__name__,
            )

            # 완료 처리
            universal_crawl_service.mark_completed(db, request_id, crawled_page.id)

            logger.info(
                f"Universal 크롤링 완료: request_id={request_id}, "
                f"page_id={crawled_page.id}, title={crawled_page.title[:50] if crawled_page.title else None}"
            )

            # auto_analyze가 True이면 AI 분석 요청 생성
            if request.auto_analyze:
                try:
                    from app.services.universal_crawl_analyzer import UniversalCrawlAnalyzerService
                    analyzer = UniversalCrawlAnalyzerService(db)
                    analyzer.create_analysis_request(crawled_page.id, requested_by="worker")
                    logger.info(f"AI 분석 요청 생성: page_id={crawled_page.id}")
                except Exception as e:
                    logger.warning(f"AI 분석 요청 생성 실패: {e}")

        except Exception as e:
            logger.error(f"Universal 크롤링 실패: request_id={request_id}, error={e}", exc_info=True)
            try:
                universal_crawl_service.mark_failed(db, request_id, str(e))
            except Exception:
                pass
        finally:
            self._update_worker_state("idle")
            db.close()


# 전역 워커 인스턴스
worker_instance: CrawlWorker = None


def handle_exception(loop, context):
    """asyncio 루프에서 처리되지 않은 예외 핸들러."""
    msg = context.get("exception", context.get("message", "Unknown error"))
    task = context.get("task")

    if task:
        logger.error(f"[ASYNC-ERROR] 처리되지 않은 예외 (task: {task.get_name()}): {msg}")
    else:
        logger.error(f"[ASYNC-ERROR] 처리되지 않은 예외: {msg}")

    exception = context.get("exception")
    if exception:
        import traceback
        tb_str = ''.join(traceback.format_exception(type(exception), exception, exception.__traceback__))
        logger.error(f"[ASYNC-ERROR] Traceback:\n{tb_str}")


async def main():
    """워커 메인 함수."""
    global worker_instance

    # asyncio 예외 핸들러 설정
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(handle_exception)

    logger.info("=" * 50)
    logger.info("통합 크롤링 워커 프로세스 시작")
    logger.info(f"PID: {os.getpid()}")
    logger.info(f"Python 버전: {sys.version}")
    logger.info("=" * 50)

    worker_instance = CrawlWorker()

    # 시그널 핸들러 설정
    def signal_handler(signum, frame):
        logger.info(f"종료 시그널 수신: {signum}")
        asyncio.create_task(worker_instance.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await worker_instance.start()
    except asyncio.CancelledError:
        logger.info("워커 태스크 취소됨")
    except Exception as e:
        logger.critical(f"워커 치명적 오류: {e}", exc_info=True)
        if worker_instance:
            try:
                await worker_instance.stop()
            except Exception:
                pass
        sys.exit(1)
    finally:
        logger.info("통합 크롤링 워커 프로세스 종료")


if __name__ == "__main__":
    asyncio.run(main())

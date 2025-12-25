"""
통합 크롤링 워커 프로세스

API 서버와 분리되어 독립적으로 크롤링 작업을 수행합니다.

실행 방법:
    python -m app.worker.instagram_worker

주요 기능:
    - Instagram Pending 크롤링 요청 처리 (InstagramCrawlRequest)
    - Universal Pending 크롤링 요청 처리 (UniversalCrawlRequest)
    - 스케줄 기반 자동 크롤링 실행 (InstagramScheduler)
    - 로그인 상태 확인 및 실패 처리
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
    log_prefix="instagram_worker",
    log_dir=Path("logs"),
    level=logging.DEBUG
)
logger.info(f"Instagram 워커 비동기 로거 초기화 완료 - 로그 파일: {logger.log_file}")

# 모듈 import
try:
    logger.info("모듈 import 시작...")

    from app.config import settings
    logger.debug("app.config import 완료")

    from app.database import SessionLocal
    logger.debug("app.database import 완료")

    from app.models import Account, InstagramCrawlRequest, InstagramCrawlRun, InstagramScheduleConfig
    logger.debug("app.models import 완료")

    from app.modules.instagram.services.request_service import CrawlRequestService
    from app.modules.instagram.services.crawl_service import CrawlService
    from app.modules.instagram.services.scheduler import InstagramScheduler
    from app.modules.instagram.services.crawler import InstagramCrawler, CrawlOptions
    from app.modules.instagram.services.worker_status_service import WorkerStatusService
    from app.modules.instagram.models.schemas import TimeWindow
    logger.debug("instagram services import 완료")

    from app.shared.browser.context_manager import ContextManager
    logger.debug("browser_service import 완료")

    from app.models.universal_crawl import UniversalCrawlRequest
    from app.services.universal_crawl_service import universal_crawl_service
    from app.services.extractors import ExtractorFactory
    logger.debug("universal_crawl import 완료")

    # Instagram 관련 로거들이 워커 로거와 같은 핸들러를 사용하도록 설정
    # 이렇게 하면 크롤러/서비스의 로그도 워커 로그 파일에 기록됨
    worker_handlers = logger.handlers
    for logger_name in ['instagram.crawler', 'instagram.crawl_service', 'instagram.post_service']:
        sub_logger = logging.getLogger(logger_name)
        sub_logger.setLevel(logging.DEBUG)
        for handler in worker_handlers:
            sub_logger.addHandler(handler)
        sub_logger.propagate = False  # 중복 로깅 방지
    logger.debug("Instagram 서브 로거 설정 완료")

    logger.info("모든 모듈 import 완료")

except Exception as e:
    import traceback
    logger.critical(f"모듈 import 중 치명적 오류: {e}")
    logger.critical(f"Traceback:\n{traceback.format_exc()}")
    AsyncLoggerManager.shutdown()
    sys.exit(1)


class InstagramWorker:
    """Instagram 크롤링 워커."""

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
        self.check_interval = 30  # 30초마다 체크
        self.pid = os.getpid()
        self.start_time: datetime = None
        self.worker_id: str = None  # 워커 상태 추적용

        # 계정별 페이지 사용 Lock (동시 크롤링 방지)
        self._page_locks: dict[int, asyncio.Lock] = {}
        self._page_locks_lock = asyncio.Lock()  # Lock 딕셔너리 접근용

    async def start(self):
        """워커 시작."""
        logger.info(f"Instagram 워커 시작 (PID: {self.pid})")
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
        logger.info("Instagram 워커 종료 요청")
        self.shutdown_event.set()

    async def _initialize(self):
        """초기화."""
        logger.info("Instagram 워커 초기화 시작")

        # 오래된 processing 요청 정리 (좀비 요청 방지)
        self._cleanup_stale_requests()

        # 기존 브라우저 프로필 Lock 정리 (비정상 종료 후 재시작 시)
        self._cleanup_stale_browser_locks()

        # 브라우저 컨텍스트 매니저는 크롤링 시 lazy 초기화
        # (메인 워커와 같은 프로필 충돌 방지를 위해 계정별 프로필 사용)
        self.context_manager = None

        logger.info("Instagram 워커 초기화 완료")

    def _cleanup_stale_browser_locks(self):
        """비정상 종료된 브라우저의 Lock 파일 및 프로세스 정리.

        이전 워커가 비정상 종료되면 브라우저 프로세스가 남아있거나
        Lock 파일이 남아서 새 브라우저를 열지 못하는 문제 해결.

        강제 종료: 해당 프로필을 사용하는 Chromium 프로세스를 직접 종료합니다.
        """
        from app.config import settings

        profile_base = Path(settings.DATA_DIR) / settings.BROWSER_PROFILES_DIR

        if not profile_base.exists():
            return

        try:
            # 1. 먼저 해당 프로필을 사용하는 모든 Chromium 프로세스 종료
            killed_count = self._kill_chromium_for_profiles(profile_base)
            if killed_count > 0:
                logger.info(f"기존 Chromium 프로세스 {killed_count}개 종료됨")
                # 프로세스 종료 후 잠시 대기
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
        """프로필 디렉토리를 사용하는 Chromium 프로세스 종료.

        Args:
            profile_base: 브라우저 프로필 기본 디렉토리

        Returns:
            종료된 프로세스 수
        """
        killed_count = 0

        try:
            if sys.platform == "win32":
                # Windows: tasklist + taskkill 사용
                # ms-playwright chromium 프로세스 중 browser_profiles를 사용하는 것만 종료
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
                                # PID 추출 (CSV 형식: "이미지 이름","PID","세션 이름",...)
                                parts = line.split(',')
                                if len(parts) > 1:
                                    pid_str = parts[1].strip('"')
                                    if pid_str.isdigit():
                                        pid = int(pid_str)
                                        # 해당 PID가 browser_profiles를 사용하는지 확인
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
                # Linux/Mac: pkill 사용
                subprocess.run(
                    ["pkill", "-f", str(profile_base)],
                    capture_output=True,
                    timeout=5
                )
                killed_count = 1  # 정확한 수를 알 수 없음

        except subprocess.TimeoutExpired:
            logger.warning("Chromium 종료 타임아웃")
        except Exception as e:
            logger.warning(f"Chromium 종료 오류: {e}")

        return killed_count

    def _is_chromium_using_profile(self, pid: int, profile_base: Path) -> bool:
        """특정 PID의 Chromium이 해당 프로필 경로를 사용하는지 확인.

        Args:
            pid: 프로세스 ID
            profile_base: 프로필 기본 디렉토리

        Returns:
            사용 중이면 True
        """
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
                    # browser_profiles 디렉토리 또는 ms-playwright를 사용하는 경우
                    profile_str = str(profile_base).lower().replace('\\', '/')
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
        """프로필 디렉토리의 Lock 파일들 제거.

        Args:
            profile_dir: 브라우저 프로필 디렉토리
        """
        lock_files = [
            "SingletonLock",
            "SingletonSocket",
            "SingletonCookie",
        ]

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
        """오래된 processing 상태 요청 정리.

        워커가 크롤링 중 비정상 종료되면 요청이 processing 상태로 남을 수 있음.
        이런 좀비 요청이 있으면 스케줄 실행이 차단되므로 시작 시 정리합니다.
        """
        db = SessionLocal()
        try:
            request_service = CrawlRequestService(db)
            cleaned = request_service.cleanup_stale_processing_requests(timeout_minutes=30)
            if cleaned > 0:
                logger.info(f"시작 시 {cleaned}개의 오래된 processing 요청 정리 완료")
        except Exception as e:
            logger.error(f"Stale request 정리 오류: {e}")
        finally:
            db.close()

    async def _cleanup(self):
        """정리."""
        logger.info("Instagram 워커 정리 시작")

        # 워커 상태를 종료로 표시
        self._mark_worker_dead()

        if self.context_manager:
            try:
                await self.context_manager.close_all_contexts()
            except Exception as e:
                logger.error(f"브라우저 컨텍스트 정리 오류: {e}")

        logger.info("Instagram 워커 정리 완료")
        AsyncLoggerManager.shutdown()

    async def _main_loop(self):
        """메인 루프."""
        logger.info(f"메인 루프 시작 (체크 간격: {self.check_interval}초)")

        while not self.shutdown_event.is_set():
            try:
                # Heartbeat 업데이트
                self._update_heartbeat()

                # 1. Instagram Pending 요청 처리
                await self._process_pending_requests()

                # 2. Universal Pending 요청 처리
                await self._process_universal_requests()

                # 3. 스케줄 기반 실행 (Instagram)
                await self._check_scheduled_runs()

                # 4. 대기 (continue_event 또는 shutdown_event 발생 시 즉시 깨어남)
                self.continue_event.clear()
                shutdown_task = asyncio.create_task(self.shutdown_event.wait())
                continue_task = asyncio.create_task(self.continue_event.wait())
                try:
                    done, pending = await asyncio.wait(
                        [shutdown_task, continue_task],
                        timeout=self.check_interval,
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    # 완료되지 않은 태스크 취소
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                    if continue_task in done:
                        logger.debug("continue_event로 즉시 깨어남 - 다음 요청 처리")
                except asyncio.TimeoutError:
                    pass  # 타임아웃 = 계속 실행

            except asyncio.CancelledError:
                logger.info("메인 루프 취소됨")
                break
            except Exception as e:
                logger.error(f"메인 루프 오류: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _process_pending_requests(self):
        """Pending 요청 처리."""
        db = SessionLocal()
        try:
            request_service = CrawlRequestService(db)
            pending = request_service.get_pending_request()

            if pending:
                logger.info(f"Pending 요청 발견: id={pending.id}, account_id={pending.account_id}")
                await self._execute_crawl(pending, db)

        except Exception as e:
            logger.error(f"Pending 요청 처리 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _check_scheduled_runs(self):
        """스케줄 기반 실행 확인."""
        db = SessionLocal()
        try:
            crawl_service = CrawlService(db)
            config = crawl_service.get_schedule_config()

            if not config or not config.enabled:
                return

            if not config.account_id:
                logger.debug("스케줄 config에 account_id 미설정")
                return

            # 스케줄러 생성
            time_windows = [
                TimeWindow(**tw) for tw in (config.time_windows or [])
            ]
            scheduler = InstagramScheduler(
                daily_runs=config.daily_runs,
                time_windows=time_windows,
            )

            # 마지막 실행 시간 조회
            last_run = crawl_service.get_last_run(account_id=config.account_id)
            last_run_time = last_run.started_at if last_run else None

            # 실행 필요 확인
            min_interval = getattr(config, 'min_interval_hours', 2) or 2
            if scheduler.should_run_now(
                last_run=last_run_time,
                min_interval_hours=min_interval,
            ):
                logger.info(f"스케줄 실행 시간 도래: account_id={config.account_id}")

                # 이미 pending 요청이 있는지 확인
                request_service = CrawlRequestService(db)
                if request_service.has_active_request(config.account_id):
                    logger.info("이미 활성 요청 존재, 스킵")
                    return

                # 요청 생성 후 실행
                request = request_service.create_request(
                    account_id=config.account_id,
                    requested_by="scheduler",
                )
                await self._execute_crawl(request, db)

        except Exception as e:
            logger.error(f"스케줄 체크 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _get_page_for_account(self, account_id: int = None):
        """계정별 브라우저 페이지 가져오기.

        ContextManager를 사용하여 계정별 프로필로 브라우저를 생성합니다.
        탭을 재사용하여 about:blank 탭이 누적되는 것을 방지합니다.

        Args:
            account_id: 계정 ID (None이면 기본 계정 사용)
        """
        if self.context_manager is None:
            logger.info("ContextManager 초기화")
            self.context_manager = ContextManager()

        # 계정별 브라우저 컨텍스트 가져오기
        logger.info(f"계정 {account_id}용 브라우저 컨텍스트 가져오기")
        context = await self.context_manager.get_or_create_context(account_id)

        # 페이지 가져오기 - 기존 페이지 재사용 우선
        pages = context.pages
        page = None

        if pages:
            # 유효한 페이지 찾기 (닫히지 않은 페이지)
            for p in pages:
                try:
                    if not p.is_closed():
                        page = p
                        logger.debug(f"기존 페이지 재사용 (account_id={account_id}, url={p.url[:50] if p.url else 'blank'}...)")
                        break
                except Exception:
                    continue

            # 불필요한 추가 탭 정리 (about:blank 상태인 탭)
            if len(pages) > 1:
                for p in pages[1:]:
                    try:
                        if not p.is_closed() and p.url == "about:blank":
                            await p.close()
                            logger.info(f"불필요한 about:blank 탭 정리 (account_id={account_id})")
                    except Exception as e:
                        logger.debug(f"탭 정리 중 오류 (무시): {e}")

        # 유효한 페이지가 없으면 새로 생성
        if page is None:
            page = await context.new_page()
            logger.info(f"새 페이지 생성 (account_id={account_id})")

        return page

    async def _get_page_lock(self, account_id: int) -> asyncio.Lock:
        """계정별 페이지 Lock을 가져오거나 생성합니다."""
        async with self._page_locks_lock:
            if account_id not in self._page_locks:
                self._page_locks[account_id] = asyncio.Lock()
            return self._page_locks[account_id]

    def _is_browser_closed_error(self, error: Exception) -> bool:
        """브라우저 closed 에러인지 확인.

        Args:
            error: 발생한 예외

        Returns:
            브라우저 closed 에러면 True
        """
        error_msg = str(error).lower()
        return any(keyword.lower() in error_msg for keyword in self.BROWSER_CLOSED_KEYWORDS)

    async def _recreate_browser_context(self, account_id: int = None):
        """브라우저 컨텍스트 재생성.

        기존 컨텍스트와 Chromium 프로세스를 정리하고 새로 생성합니다.

        Args:
            account_id: 계정 ID
        """
        logger.info(f"브라우저 컨텍스트 재생성 시작 (account_id={account_id})")

        # 1. 기존 컨텍스트 닫기
        if self.context_manager:
            try:
                await self.context_manager.close_context(account_id)
                logger.info(f"기존 컨텍스트 닫기 완료 (account_id={account_id})")
            except Exception as e:
                logger.warning(f"기존 컨텍스트 닫기 실패 (무시): {e}")

            # ContextManager 자체도 초기화 (Playwright 인스턴스 재생성 유도)
            try:
                await self.context_manager.close_all_contexts()
                self.context_manager = None
                logger.info("ContextManager 초기화 완료")
            except Exception as e:
                logger.warning(f"ContextManager 초기화 실패 (무시): {e}")
                self.context_manager = None

        # 2. 잔여 Chromium 프로세스 정리
        from app.config import settings
        profile_base = Path(settings.DATA_DIR) / settings.BROWSER_PROFILES_DIR
        killed = self._kill_chromium_for_profiles(profile_base)
        if killed > 0:
            logger.info(f"잔여 Chromium 프로세스 {killed}개 종료")

        # 3. Lock 파일 정리
        for profile_dir in profile_base.iterdir():
            if profile_dir.is_dir():
                self._remove_lock_files(profile_dir)

        # 4. 충분히 대기 (Chromium 프로세스 종료 및 Lock 해제 대기)
        await asyncio.sleep(3)

        logger.info(f"브라우저 컨텍스트 재생성 준비 완료 (account_id={account_id})")

    async def _execute_crawl(self, request: InstagramCrawlRequest, db):
        """크롤링 실행."""
        request_service = CrawlRequestService(db)
        crawl_service = CrawlService(db)

        # 처리 중으로 변경
        request_service.mark_processing(request.id)

        # 요청 타입에 따라 분기
        request_type = getattr(request, 'request_type', 'feed') or 'feed'
        logger.info(f"크롤링 시작: request_id={request.id}, type={request_type}")

        if request_type == "single_post":
            await self._execute_single_post_recrawl(request, db, request_service, crawl_service)
        elif request_type == "single_post_url":
            await self._execute_url_crawl(request, db, request_service, crawl_service)
        else:
            await self._execute_feed_crawl(request, db, request_service, crawl_service)

    async def _execute_feed_crawl(self, request: InstagramCrawlRequest, db, request_service, crawl_service):
        """피드 크롤링 실행."""
        max_retries = 3  # 브라우저 에러 시 재시도 횟수 (복구 기회 충분히 제공)
        retry_count = 0

        # 계정별 Lock 획득 (동시 크롤링 방지)
        page_lock = await self._get_page_lock(request.account_id)

        async with page_lock:
            logger.debug(f"페이지 Lock 획득 (account_id={request.account_id}, type=feed)")

            while retry_count <= max_retries:
                try:
                    # 로그인 상태 확인
                    account = db.query(Account).filter(Account.id == request.account_id).first()
                    if not account:
                        request_service.mark_failed(request.id, "계정을 찾을 수 없음")
                        logger.warning(f"계정 없음: account_id={request.account_id}")
                        return

                    if not account.is_logged_in:
                        request_service.mark_failed(request.id, "로그인 필요")
                        logger.warning(f"로그인 필요: account={account.name}")
                        return

                    # 워커 상태를 crawling으로 변경
                    self._update_worker_state("crawling", account.name)

                    # 계정별 브라우저 페이지 가져오기
                    page = await self._get_page_for_account(account.id)

                    # 인스타그램 피드 페이지로 이동
                    logger.info("인스타그램 피드 페이지로 이동 중...")
                    await page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
                    await page.wait_for_timeout(2000)  # 페이지 로드 대기
                    logger.info(f"인스타그램 페이지 로드 완료: {page.url}")

                    # 크롤러 생성 (Page 객체 전달)
                    crawler = InstagramCrawler(page)
                    logger.info("InstagramCrawler 생성 완료, 크롤링 시작...")

                    # 크롤링 실행
                    crawl_run = await crawl_service.run_crawl(
                        crawler=crawler,
                        account_id=request.account_id,
                    )

                    # 워커 상태 업데이트 (run_id 포함)
                    self._update_worker_state("crawling", account.name, crawl_run.id)

                    logger.info(f"크롤링 완료: success={crawl_run.success}, collected={crawl_run.total_collected}, new={crawl_run.new_saved}")

                    # 완료 처리
                    if crawl_run.success:
                        request_service.mark_completed(request.id, crawl_run.id)
                        logger.info(
                            f"크롤링 완료: request_id={request.id}, "
                            f"collected={crawl_run.total_collected}, new={crawl_run.new_saved}"
                        )
                    else:
                        request_service.mark_failed(request.id, crawl_run.error_message or "크롤링 실패")
                        logger.warning(f"크롤링 실패: {crawl_run.error_message}")

                    # 성공 시 루프 종료
                    return

                except Exception as e:
                    # 브라우저 closed 에러면 재시도
                    if self._is_browser_closed_error(e) and retry_count < max_retries:
                        retry_count += 1
                        logger.warning(f"브라우저 closed 에러 감지, 브라우저 재생성 후 재시도 ({retry_count}/{max_retries}): {e}")
                        await self._recreate_browser_context(request.account_id)
                        continue

                    request_service.mark_failed(request.id, str(e))
                    logger.error(f"크롤링 예외: {e}", exc_info=True)
                    return
                finally:
                    # 워커 상태를 idle로 복원
                    self._update_worker_state("idle")
                    # 대기 중인 요청이 있으면 즉시 처리하도록 이벤트 설정
                    self.continue_event.set()

    async def _execute_single_post_recrawl(self, request: InstagramCrawlRequest, db, request_service, crawl_service):
        """개별 게시물 재크롤링 실행."""
        max_retries = 3  # 브라우저 에러 시 재시도 횟수 (복구 기회 충분히 제공)
        retry_count = 0

        # 계정별 Lock 획득 (동시 크롤링 방지)
        page_lock = await self._get_page_lock(request.account_id)

        async with page_lock:
            logger.debug(f"페이지 Lock 획득 (account_id={request.account_id}, type=single_post)")

            while retry_count <= max_retries:
                try:
                    # 대상 게시물 ID 확인
                    target_post_id = getattr(request, 'target_post_id', None)
                    if not target_post_id:
                        request_service.mark_failed(request.id, "대상 게시물 ID 없음")
                        logger.warning(f"대상 게시물 ID 없음: request_id={request.id}")
                        return

                    # 로그인 상태 확인
                    account = db.query(Account).filter(Account.id == request.account_id).first()
                    if not account:
                        request_service.mark_failed(request.id, "계정을 찾을 수 없음")
                        logger.warning(f"계정 없음: account_id={request.account_id}")
                        return

                    if not account.is_logged_in:
                        request_service.mark_failed(request.id, "로그인 필요")
                        logger.warning(f"로그인 필요: account={account.name}")
                        return

                    # 워커 상태를 recrawling으로 변경
                    self._update_worker_state("recrawling", account.name)

                    # 계정별 브라우저 페이지 가져오기
                    page = await self._get_page_for_account(account.id)

                    # 크롤러 생성
                    crawler = InstagramCrawler(page)
                    logger.info(f"개별 게시물 재크롤링 시작: post_id={target_post_id}")

                    # 재크롤링 실행
                    result = await crawl_service.recrawl_single_post(
                        crawler=crawler,
                        post_id=target_post_id,
                    )

                    if result["success"]:
                        # 성공 시 완료 처리 (crawl_run_id는 없음)
                        request.status = "completed"
                        request.processed_at = datetime.now()
                        db.commit()
                        logger.info(f"재크롤링 완료: request_id={request.id}, post_id={target_post_id}")
                    else:
                        request_service.mark_failed(request.id, result["message"])
                        logger.warning(f"재크롤링 실패: {result['message']}")

                    # 성공 시 루프 종료
                    return

                except Exception as e:
                    # 브라우저 closed 에러면 재시도
                    if self._is_browser_closed_error(e) and retry_count < max_retries:
                        retry_count += 1
                        logger.warning(f"브라우저 closed 에러 감지, 브라우저 재생성 후 재시도 ({retry_count}/{max_retries}): {e}")
                        await self._recreate_browser_context(request.account_id)
                        continue

                    request_service.mark_failed(request.id, str(e))
                    logger.error(f"재크롤링 예외: {e}", exc_info=True)
                    return
                finally:
                    # 워커 상태를 idle로 복원
                    self._update_worker_state("idle")
                    # 대기 중인 요청이 있으면 즉시 처리하도록 이벤트 설정
                    self.continue_event.set()

    async def _execute_url_crawl(self, request: InstagramCrawlRequest, db, request_service, crawl_service):
        """URL로 단일 게시물 수집 실행."""
        max_retries = 3  # 브라우저 에러 시 재시도 횟수 (복구 기회 충분히 제공)
        retry_count = 0

        # 계정별 Lock 획득 (동시 크롤링 방지)
        page_lock = await self._get_page_lock(request.account_id)

        async with page_lock:
            logger.debug(f"페이지 Lock 획득 (account_id={request.account_id}, type=url_crawl)")

            while retry_count <= max_retries:
                try:
                    # 대상 URL 확인
                    target_url = getattr(request, 'target_url', None)
                    if not target_url:
                        request_service.mark_failed(request.id, "대상 URL 없음")
                        logger.warning(f"대상 URL 없음: request_id={request.id}")
                        return

                    # 로그인 상태 확인
                    account = db.query(Account).filter(Account.id == request.account_id).first()
                    if not account:
                        request_service.mark_failed(request.id, "계정을 찾을 수 없음")
                        logger.warning(f"계정 없음: account_id={request.account_id}")
                        return

                    if not account.is_logged_in:
                        request_service.mark_failed(request.id, "로그인 필요")
                        logger.warning(f"로그인 필요: account={account.name}")
                        return

                    # 워커 상태를 crawling으로 변경
                    self._update_worker_state("crawling", account.name)

                    # 계정별 브라우저 페이지 가져오기
                    page = await self._get_page_for_account(account.id)

                    # 크롤러 생성
                    crawler = InstagramCrawler(page)
                    logger.info(f"URL 크롤링 시작: url={target_url}")

                    # URL 크롤링 실행
                    result = await crawl_service.crawl_by_url(
                        crawler=crawler,
                        url=target_url,
                        account_id=request.account_id,
                    )

                    if result["success"]:
                        # 성공 시 완료 처리
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

                    # 성공 시 루프 종료
                    return

                except Exception as e:
                    # 브라우저 closed 에러면 재시도
                    if self._is_browser_closed_error(e) and retry_count < max_retries:
                        retry_count += 1
                        logger.warning(f"브라우저 closed 에러 감지, 브라우저 재생성 후 재시도 ({retry_count}/{max_retries}): {e}")
                        await self._recreate_browser_context(request.account_id)
                        continue

                    request_service.mark_failed(request.id, str(e))
                    logger.error(f"URL 크롤링 예외: {e}", exc_info=True)
                    return
                finally:
                    # 워커 상태를 idle로 복원
                    self._update_worker_state("idle")
                    # 대기 중인 요청이 있으면 즉시 처리하도록 이벤트 설정
                    self.continue_event.set()

    # ========================================
    # Universal 크롤링 관련 메서드
    # ========================================

    async def _process_universal_requests(self):
        """Universal Pending 요청 처리."""
        db = SessionLocal()
        try:
            pending_list = universal_crawl_service.get_pending_requests(db, limit=1)

            if pending_list:
                pending = pending_list[0]
                logger.info(f"Universal 요청 발견: id={pending.id}, url={pending.url}")
                await self._execute_universal_crawl(pending, db)

        except Exception as e:
            logger.error(f"Universal 요청 처리 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _execute_universal_crawl(self, request: UniversalCrawlRequest, db):
        """Universal URL 크롤링 실행."""
        try:
            # 처리 중으로 변경
            universal_crawl_service.mark_processing(db, request.id)
            logger.info(f"Universal 크롤링 시작: request_id={request.id}, url={request.url}")

            # 워커 상태를 crawling으로 변경
            self._update_worker_state("universal_crawl")

            # 브라우저 페이지 가져오기
            # account_id가 있으면 해당 프로필 사용, 없으면 기본 계정 사용
            # None을 전달하면 context_manager가 기본 계정을 자동 선택
            account_id = request.account_id if request.account_id else None
            page = await self._get_page_for_account(account_id)

            # ExtractorFactory로 적절한 추출기 선택
            extractor = ExtractorFactory.get_extractor(request.url_type)
            logger.info(f"추출기 선택: {extractor.name} for url_type={request.url_type}")

            # 콘텐츠 추출
            extracted = await extractor.extract(page, request.url)

            if extracted.error:
                # 추출 실패
                universal_crawl_service.mark_failed(db, request.id, extracted.error)
                logger.warning(f"Universal 크롤링 실패: {extracted.error}")
                return

            # CrawledPage 저장
            crawled_page = universal_crawl_service.create_crawled_page(
                db=db,
                url=extracted.url,
                url_type=extracted.url_type,
                title=extracted.title,
                description=extracted.description,
                content=extracted.content,
                extracted_data=extracted.extracted_data,
                og_title=extracted.og_title,
                og_description=extracted.og_description,
                og_image=extracted.og_image,
                extractor_used=extracted.extractor_used,
            )

            # 요청 완료 처리
            universal_crawl_service.mark_completed(db, request.id, crawled_page.id)
            logger.info(
                f"Universal 크롤링 완료: request_id={request.id}, "
                f"page_id={crawled_page.id}, title={crawled_page.title}"
            )

            # TODO: auto_analyze가 True면 LLM 분석 수행
            if request.auto_analyze:
                logger.debug(f"auto_analyze 활성화, 추후 LLM 분석 예정: page_id={crawled_page.id}")

        except Exception as e:
            universal_crawl_service.mark_failed(db, request.id, str(e))
            logger.error(f"Universal 크롤링 예외: {e}", exc_info=True)
        finally:
            # 워커 상태를 idle로 복원
            self._update_worker_state("idle")
            # 대기 중인 요청이 있으면 즉시 처리하도록 이벤트 설정
            self.continue_event.set()


# 전역 워커 인스턴스
worker_instance: InstagramWorker = None


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
    logger.info("Instagram 크롤링 워커 프로세스 시작")
    logger.info(f"PID: {os.getpid()}")
    logger.info(f"Python 버전: {sys.version}")
    logger.info("=" * 50)

    worker_instance = InstagramWorker()

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
        logger.info("Instagram 워커 프로세스 종료")


if __name__ == "__main__":
    asyncio.run(main())

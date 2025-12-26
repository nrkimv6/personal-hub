"""
Instagram 크롤링 워커 프로세스

API 서버와 분리되어 독립적으로 Instagram 크롤링 작업을 수행합니다.

실행 방법:
    python -m app.worker.instagram_worker

주요 기능:
    - Pending 크롤링 요청 처리 (InstagramCrawlRequest)
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
    from app.shared.browser.tab_pool_manager import TabPoolManager
    logger.debug("browser_service import 완료")

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
        self.tab_pool_manager: TabPoolManager = None
        self.check_interval = 30  # 30초마다 체크
        self.pid = os.getpid()
        self.start_time: datetime = None
        self.worker_id: str = None  # 워커 상태 추적용

        # 백그라운드 태스크 관리 (병렬 크롤링용)
        self._running_tasks: set = set()

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
        """워커 종료 시 정리."""
        logger.info("Instagram 워커 정리 시작")

        # 1. 실행 중인 태스크 취소
        if self._running_tasks:
            logger.info(f"실행 중인 태스크 {len(self._running_tasks)}개 취소 중...")
            for task in self._running_tasks:
                if not task.done():
                    task.cancel()

            # 태스크 완료 대기 (취소 포함)
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

        logger.info("Instagram 워커 정리 완료")
        AsyncLoggerManager.shutdown()

    async def _main_loop(self):
        """메인 루프 (비블로킹 방식).

        크롤링 요청을 백그라운드 태스크로 디스패치하여
        피드 크롤링 중에도 단일 포스트 재시도가 가능합니다.
        """
        logger.info(f"메인 루프 시작 (비블로킹 모드, 체크 간격: 1초)")

        while not self.shutdown_event.is_set():
            try:
                # Heartbeat 업데이트
                self._update_heartbeat()

                # 완료된 태스크 정리
                self._cleanup_completed_tasks()

                # 1. Instagram Pending 요청 디스패치 (백그라운드)
                await self._dispatch_pending_requests()

                # 2. 스케줄 기반 실행 디스패치 (백그라운드)
                await self._dispatch_scheduled_runs()

                # 3. 짧은 대기 (새 요청 빠르게 체크)
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

    def _is_request_running(self, request_id: int) -> bool:
        """요청이 이미 실행 중인지 확인."""
        for task in self._running_tasks:
            if task.get_name() == f"crawl_{request_id}":
                return True
        return False

    async def _dispatch_pending_requests(self):
        """Pending 요청을 백그라운드 태스크로 디스패치."""
        db = SessionLocal()
        try:
            request_service = CrawlRequestService(db)

            # 여러 pending 요청 가져오기 (최대 5개)
            pending_list = request_service.get_pending_requests(limit=5) if hasattr(request_service, 'get_pending_requests') else []

            # 단일 요청 fallback
            if not pending_list:
                pending = request_service.get_pending_request()
                if pending:
                    pending_list = [pending]

            for pending in pending_list:
                # 이미 처리 중인지 확인
                if self._is_request_running(pending.id):
                    continue

                # 백그라운드로 실행
                task = asyncio.create_task(
                    self._execute_crawl_safe(pending),
                    name=f"crawl_{pending.id}"
                )
                self._running_tasks.add(task)
                logger.info(f"크롤링 태스크 시작: request_id={pending.id}, type={getattr(pending, 'request_type', 'feed')}")

        except Exception as e:
            logger.error(f"Pending 요청 디스패치 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _dispatch_scheduled_runs(self):
        """스케줄 기반 실행을 백그라운드로 디스패치."""
        db = SessionLocal()
        try:
            crawl_service = CrawlService(db)
            config = crawl_service.get_schedule_config()

            if not config or not config.enabled:
                return

            if not config.account_id:
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

                # 요청 생성
                request = request_service.create_request(
                    account_id=config.account_id,
                    requested_by="scheduler",
                )

                # 이미 실행 중이 아니면 백그라운드로 디스패치
                if not self._is_request_running(request.id):
                    task = asyncio.create_task(
                        self._execute_crawl_safe(request),
                        name=f"crawl_{request.id}"
                    )
                    self._running_tasks.add(task)
                    logger.info(f"스케줄 크롤링 태스크 시작: request_id={request.id}")

        except Exception as e:
            logger.error(f"스케줄 디스패치 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _execute_crawl_safe(self, request: InstagramCrawlRequest):
        """안전한 크롤링 실행 (예외 처리 포함).

        각 크롤링 요청을 독립적인 DB 세션으로 처리합니다.
        """
        db = SessionLocal()
        try:
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

        except Exception as e:
            logger.error(f"크롤링 실패: request_id={request.id}, error={e}", exc_info=True)
            try:
                request_service = CrawlRequestService(db)
                request_service.mark_failed(request.id, str(e))
            except Exception:
                pass
        finally:
            db.close()

    async def _get_tab_for_request(self, request_id: int, account_id: int = None):
        """TabPoolManager를 통해 탭 획득.

        Args:
            request_id: 크롤링 요청 ID (탭 추적용)
            account_id: 계정 ID (None이면 기본 계정 사용)

        Returns:
            Page: 사용 가능한 브라우저 탭
        """
        # ContextManager 초기화 (lazy)
        if self.context_manager is None:
            logger.info("ContextManager 초기화")
            self.context_manager = ContextManager()

        # TabPoolManager 초기화 (lazy)
        if self.tab_pool_manager is None:
            logger.info("TabPoolManager 초기화")
            self.tab_pool_manager = TabPoolManager(self.context_manager)

        # TabPoolManager를 통해 탭 획득
        tab = await self.tab_pool_manager.get_tab(
            target_id=request_id,
            account_id=account_id
        )
        logger.info(f"탭 획득 완료: request_id={request_id}, account_id={account_id}")
        return tab

    async def _release_tab(self, tab):
        """사용 완료된 탭 반환.

        Args:
            tab: 반환할 브라우저 탭
        """
        if self.tab_pool_manager and tab:
            await self.tab_pool_manager.release_tab(tab)

    async def _get_page_for_account(self, account_id: int = None):
        """계정별 브라우저 페이지 가져오기.

        TabPoolManager가 아닌 직접 ContextManager 사용.

        Args:
            account_id: 계정 ID (None이면 기본 계정 사용)
        """
        if self.context_manager is None:
            logger.info("ContextManager 초기화")
            self.context_manager = ContextManager()

        # 계정별 브라우저 컨텍스트 가져오기
        context = await self.context_manager.get_or_create_context(account_id)

        # 페이지 가져오기 - 기존 페이지 재사용 우선
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

        # 유효한 페이지가 없으면 새로 생성
        if page is None:
            page = await context.new_page()

        return page

    async def _check_instagram_login(self, page) -> bool:
        """Instagram 로그인 상태 확인.

        Args:
            page: Playwright Page 객체 (Instagram 메인 페이지가 로드된 상태)

        Returns:
            로그인 되어있으면 True, 아니면 False
        """
        try:
            # 로그인 버튼이 있으면 로그아웃 상태
            login_button = await page.query_selector('a[href="/accounts/login/"]')
            if login_button:
                return False

            # 로그인 상태 확인 셀렉터들
            login_indicators = [
                'a[href*="/direct/inbox/"]',  # DM 링크
                'svg[aria-label="홈"]',  # 홈 아이콘 (한글)
                'svg[aria-label="Home"]',  # 홈 아이콘 (영문)
                'article',  # 피드 콘텐츠
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

    async def _execute_feed_crawl(self, request: InstagramCrawlRequest, db, request_service, crawl_service):
        """피드 크롤링 실행 (TabPoolManager 사용으로 병렬 처리 가능)."""
        max_retries = 3
        retry_count = 0
        tab = None

        while retry_count <= max_retries:
            try:
                # 계정 확인
                account = db.query(Account).filter(Account.id == request.account_id).first()
                if not account:
                    request_service.mark_failed(request.id, "계정을 찾을 수 없음")
                    logger.warning(f"계정 없음: account_id={request.account_id}")
                    return

                # 워커 상태를 crawling으로 변경
                self._update_worker_state("crawling", account.name)

                # TabPoolManager를 통해 탭 획득
                tab = await self._get_tab_for_request(request.id, account.id)

                # 인스타그램 피드 페이지로 이동
                logger.info("인스타그램 피드 페이지로 이동 중...")
                await tab.goto("https://www.instagram.com/", wait_until="domcontentloaded")
                await tab.wait_for_timeout(2000)
                logger.info(f"인스타그램 페이지 로드 완료: {tab.url}")

                # 실제 로그인 상태 확인 (브라우저에서)
                is_logged_in = await self._check_instagram_login(tab)
                if not is_logged_in:
                    # DB 업데이트
                    account.is_logged_in = False
                    db.commit()
                    request_service.mark_failed(request.id, "Instagram 로그인 필요")
                    logger.warning(f"Instagram 로그인 필요: account={account.name}")
                    return
                else:
                    # 로그인 상태 업데이트
                    account.is_logged_in = True
                    db.commit()

                # 크롤러 생성 (Page 객체 전달)
                crawler = InstagramCrawler(tab)
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

                return

            except Exception as e:
                if self._is_browser_closed_error(e) and retry_count < max_retries:
                    retry_count += 1
                    logger.warning(f"브라우저 closed 에러 감지, 재시도 ({retry_count}/{max_retries}): {e}")
                    # 탭 반환 후 재시도
                    if tab:
                        await self._release_tab(tab)
                        tab = None
                    await self._recreate_browser_context(request.account_id)
                    continue

                request_service.mark_failed(request.id, str(e))
                logger.error(f"크롤링 예외: {e}", exc_info=True)
                return
            finally:
                # 탭 반환 (필수!)
                if tab:
                    await self._release_tab(tab)
                self._update_worker_state("idle")

    async def _execute_single_post_recrawl(self, request: InstagramCrawlRequest, db, request_service, crawl_service):
        """개별 게시물 재크롤링 실행 (TabPoolManager 사용, 병렬 처리 가능)."""
        max_retries = 3
        retry_count = 0
        tab = None

        while retry_count <= max_retries:
            try:
                # 대상 게시물 ID 확인
                target_post_id = getattr(request, 'target_post_id', None)
                if not target_post_id:
                    request_service.mark_failed(request.id, "대상 게시물 ID 없음")
                    logger.warning(f"대상 게시물 ID 없음: request_id={request.id}")
                    return

                # 계정 확인
                account = db.query(Account).filter(Account.id == request.account_id).first()
                if not account:
                    request_service.mark_failed(request.id, "계정을 찾을 수 없음")
                    logger.warning(f"계정 없음: account_id={request.account_id}")
                    return

                # 워커 상태를 recrawling으로 변경
                self._update_worker_state("recrawling", account.name)

                # TabPoolManager를 통해 탭 획득
                tab = await self._get_tab_for_request(request.id, account.id)

                # 실제 로그인 상태 확인 (브라우저에서)
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

                # 크롤러 생성
                crawler = InstagramCrawler(tab)
                logger.info(f"개별 게시물 재크롤링 시작: post_id={target_post_id}")

                # 재크롤링 실행
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
                    await self._recreate_browser_context(request.account_id)
                    continue

                request_service.mark_failed(request.id, str(e))
                logger.error(f"재크롤링 예외: {e}", exc_info=True)
                return
            finally:
                if tab:
                    await self._release_tab(tab)
                self._update_worker_state("idle")

    async def _execute_url_crawl(self, request: InstagramCrawlRequest, db, request_service, crawl_service):
        """URL로 단일 게시물 수집 실행 (TabPoolManager 사용, 병렬 처리 가능)."""
        max_retries = 3
        retry_count = 0
        tab = None

        while retry_count <= max_retries:
            try:
                # 대상 URL 확인
                target_url = getattr(request, 'target_url', None)
                if not target_url:
                    request_service.mark_failed(request.id, "대상 URL 없음")
                    logger.warning(f"대상 URL 없음: request_id={request.id}")
                    return

                # 계정 확인
                account = db.query(Account).filter(Account.id == request.account_id).first()
                if not account:
                    request_service.mark_failed(request.id, "계정을 찾을 수 없음")
                    logger.warning(f"계정 없음: account_id={request.account_id}")
                    return

                # 워커 상태를 crawling으로 변경
                self._update_worker_state("crawling", account.name)

                # TabPoolManager를 통해 탭 획득
                tab = await self._get_tab_for_request(request.id, account.id)

                # 실제 로그인 상태 확인 (브라우저에서)
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

                # 크롤러 생성
                crawler = InstagramCrawler(tab)
                logger.info(f"URL 크롤링 시작: url={target_url}")

                # URL 크롤링 실행
                result = await crawl_service.crawl_by_url(
                    crawler=crawler,
                    url=target_url,
                    account_id=request.account_id,
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
                    await self._recreate_browser_context(request.account_id)
                    continue

                request_service.mark_failed(request.id, str(e))
                logger.error(f"URL 크롤링 예외: {e}", exc_info=True)
                return
            finally:
                if tab:
                    await self._release_tab(tab)
                self._update_worker_state("idle")


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

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
    from app.modules.instagram.models.schemas import TimeWindow
    logger.debug("instagram services import 완료")

    from app.shared.browser.browser_service import BrowserService
    logger.debug("browser_service import 완료")

    logger.info("모든 모듈 import 완료")

except Exception as e:
    import traceback
    logger.critical(f"모듈 import 중 치명적 오류: {e}")
    logger.critical(f"Traceback:\n{traceback.format_exc()}")
    AsyncLoggerManager.shutdown()
    sys.exit(1)


class InstagramWorker:
    """Instagram 크롤링 워커."""

    def __init__(self):
        self.shutdown_event = asyncio.Event()
        self.browser_service: BrowserService = None
        self.check_interval = 30  # 30초마다 체크
        self.pid = os.getpid()
        self.start_time: datetime = None

    async def start(self):
        """워커 시작."""
        logger.info(f"Instagram 워커 시작 (PID: {self.pid})")
        self.start_time = datetime.now()

        try:
            await self._initialize()
            await self._main_loop()
        finally:
            await self._cleanup()

    async def stop(self):
        """워커 종료."""
        logger.info("Instagram 워커 종료 요청")
        self.shutdown_event.set()

    async def _initialize(self):
        """초기화."""
        logger.info("Instagram 워커 초기화 시작")

        # 브라우저 서비스 초기화
        self.browser_service = BrowserService()
        await self.browser_service.initialize()

        logger.info("Instagram 워커 초기화 완료")

    async def _cleanup(self):
        """정리."""
        logger.info("Instagram 워커 정리 시작")

        if self.browser_service:
            try:
                await self.browser_service.perform_global_cleanup()
            except Exception as e:
                logger.error(f"브라우저 서비스 정리 오류: {e}")

        logger.info("Instagram 워커 정리 완료")
        AsyncLoggerManager.shutdown()

    async def _main_loop(self):
        """메인 루프."""
        logger.info(f"메인 루프 시작 (체크 간격: {self.check_interval}초)")

        while not self.shutdown_event.is_set():
            try:
                # 1. Pending 요청 처리
                await self._process_pending_requests()

                # 2. 스케줄 기반 실행
                await self._check_scheduled_runs()

                # 3. 대기
                try:
                    await asyncio.wait_for(
                        self.shutdown_event.wait(),
                        timeout=self.check_interval
                    )
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

    async def _execute_crawl(self, request: InstagramCrawlRequest, db):
        """크롤링 실행."""
        request_service = CrawlRequestService(db)
        crawl_service = CrawlService(db)

        # 처리 중으로 변경
        request_service.mark_processing(request.id)
        logger.info(f"크롤링 시작: request_id={request.id}")

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

            # 크롤러 생성
            crawler = InstagramCrawler(self.browser_service, account.id)

            # 크롤링 실행
            crawl_run = await crawl_service.run_crawl(
                crawler=crawler,
                account_id=request.account_id,
            )

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

        except Exception as e:
            request_service.mark_failed(request.id, str(e))
            logger.error(f"크롤링 예외: {e}", exc_info=True)


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

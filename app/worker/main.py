"""
통합 워커 메인 진입점.

WorkerOrchestrator를 사용하여 모든 워커를 관리합니다:
- NaverMonitorWorker: 네이버 예약 모니터링/스나이핑
- ScheduledCrawlWorker: 스케줄 기반 Instagram 피드 크롤링
- OnDemandCrawlWorker: 온디맨드 (Instagram 개별 + Universal) 크롤링
- GoogleSearchWorker: Google 검색 큐 처리

실행 방법:
    python -m app.worker.main                  # 모든 워커 실행
    python -m app.worker.main --naver          # 네이버 워커만
    python -m app.worker.main --scheduled      # 스케줄 워커만
    python -m app.worker.main --ondemand       # 온디맨드 워커만
    python -m app.worker.main --google         # Google 검색 워커만
    python -m app.worker.main --crawl          # 크롤 워커만 (scheduled + ondemand)

주요 기능:
    - WorkerOrchestrator를 통한 중앙 집중식 워커 관리
    - BrowserManager 공유 (한 프로세스에서 하나의 브라우저)
    - 4계층 예외 격리 아키텍처
    - 시그널 핸들링 (SIGINT, SIGTERM)
"""
import asyncio
import sys
import os
import signal
import logging
import argparse
from pathlib import Path

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 비동기 로거 설정
from app.utils.async_logger import AsyncLoggerManager

# APP_MODE에 따라 로그 디렉토리 결정
is_dev = os.environ.get("APP_MODE") == "development"
log_dir = Path("logs/dev") if is_dev else Path("logs")
log_dir.mkdir(parents=True, exist_ok=True)

# 워커 전용 비동기 로거 설정
logger = AsyncLoggerManager.setup_worker_logger(
    log_prefix="worker",
    log_dir=log_dir,
    level=logging.DEBUG
)
logger.info(f"통합 워커 로거 초기화 완료 - 로그 파일: {logger.log_file}")

# 모듈 import
try:
    logger.info("모듈 import 시작...")

    from app.worker.orchestrator import WorkerOrchestrator
    from app.worker.naver_monitor_worker import NaverMonitorWorker
    from app.worker.scheduled_worker import ScheduledCrawlWorker
    from app.worker.ondemand_worker import OnDemandCrawlWorker
    from app.worker.google_search_worker import GoogleSearchWorker

    # 크롤러 및 워커 관련 로거들이 워커 로거와 같은 핸들러를 사용하도록 설정
    worker_handlers = logger.handlers
    for logger_name in [
        # 크롤러 관련
        'instagram.crawler', 'instagram.crawl_service', 'instagram.post_service', 'universal_crawl',
        # 워커 관련
        'app.shared.worker.base_worker',
        'app.worker.orchestrator',
        'app.worker.naver_monitor_worker',
        'app.worker.scheduled_worker',
        'app.worker.ondemand_worker',
        'app.worker.google_search_worker',
        'app.worker.crawl_worker_base',
        'instagram.worker_status',
        # 브라우저 관련
        'app.shared.browser.browser_manager',
        'app.shared.browser.context_manager',
        'app.shared.browser.tab_pool_manager',
    ]:
        sub_logger = logging.getLogger(logger_name)
        sub_logger.setLevel(logging.DEBUG)
        for handler in worker_handlers:
            sub_logger.addHandler(handler)
        sub_logger.propagate = False  # 중복 로깅 방지

    logger.info("모든 모듈 import 완료")

except Exception as e:
    import traceback
    logger.critical(f"모듈 import 중 치명적 오류: {e}")
    logger.critical(f"Traceback:\n{traceback.format_exc()}")
    AsyncLoggerManager.shutdown()
    sys.exit(1)


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


async def run_with_orchestrator(
    run_naver: bool = True,
    run_scheduled: bool = True,
    run_ondemand: bool = True,
    run_google: bool = True,
):
    """WorkerOrchestrator를 사용하여 워커들을 실행합니다.

    Args:
        run_naver: 네이버 워커 실행 여부
        run_scheduled: 스케줄 워커 실행 여부
        run_ondemand: 온디맨드 워커 실행 여부
        run_google: Google 검색 워커 실행 여부
    """
    orchestrator = WorkerOrchestrator()

    # 시그널 핸들러 설정
    def signal_handler(signum, frame):
        logger.info(f"종료 시그널 수신: {signum}")
        asyncio.create_task(orchestrator.shutdown())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # 오케스트레이터 초기화 (BrowserManager 초기화 포함)
        await orchestrator.initialize()

        # 워커 등록 (BrowserManager 공유)
        if run_naver:
            naver_worker = NaverMonitorWorker(
                browser_manager=orchestrator.browser_manager
            )
            orchestrator.register_worker("naver", naver_worker)
            logger.info("NaverMonitorWorker 등록됨")

        if run_scheduled:
            scheduled_worker = ScheduledCrawlWorker(
                browser_manager=orchestrator.browser_manager
            )
            orchestrator.register_worker("scheduled", scheduled_worker)
            logger.info("ScheduledCrawlWorker 등록됨")

        if run_ondemand:
            ondemand_worker = OnDemandCrawlWorker(
                browser_manager=orchestrator.browser_manager
            )
            orchestrator.register_worker("ondemand", ondemand_worker)
            logger.info("OnDemandCrawlWorker 등록됨")

        if run_google:
            google_worker = GoogleSearchWorker(
                browser_manager=orchestrator.browser_manager
            )
            orchestrator.register_worker("google_search", google_worker)
            logger.info("GoogleSearchWorker 등록됨")

        if not orchestrator.workers:
            logger.error("실행할 워커가 없습니다.")
            return

        # 모든 워커 실행
        await orchestrator.run()

    except Exception as e:
        logger.critical(f"오케스트레이터 실행 중 오류: {e}", exc_info=True)
        raise
    finally:
        await orchestrator.shutdown()


async def main(args):
    """메인 함수."""
    # asyncio 예외 핸들러 설정
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(handle_exception)

    logger.info("=" * 50)
    logger.info("통합 워커 프로세스 시작 (WorkerOrchestrator)")
    logger.info(f"PID: {os.getpid()}")
    logger.info(f"Python 버전: {sys.version}")
    logger.info(
        f"실행 모드: naver={args.naver or args.all}, "
        f"scheduled={args.scheduled or args.crawl or args.all}, "
        f"ondemand={args.ondemand or args.crawl or args.all}, "
        f"google={args.google or args.all}"
    )
    logger.info("=" * 50)

    try:
        await run_with_orchestrator(
            run_naver=args.naver or args.all,
            run_scheduled=args.scheduled or args.crawl or args.all,
            run_ondemand=args.ondemand or args.crawl or args.all,
            run_google=args.google or args.all,
        )
    except Exception as e:
        logger.critical(f"워커 치명적 오류: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("통합 워커 프로세스 종료")
        AsyncLoggerManager.shutdown()


def parse_args():
    """명령행 인자 파싱."""
    parser = argparse.ArgumentParser(description="통합 워커 (WorkerOrchestrator)")
    parser.add_argument(
        "--naver",
        action="store_true",
        help="네이버 워커만 실행",
    )
    parser.add_argument(
        "--scheduled",
        action="store_true",
        help="스케줄 워커만 실행",
    )
    parser.add_argument(
        "--ondemand",
        action="store_true",
        help="온디맨드 워커만 실행",
    )
    parser.add_argument(
        "--google",
        action="store_true",
        help="Google 검색 워커만 실행",
    )
    parser.add_argument(
        "--crawl",
        action="store_true",
        help="크롤 워커만 실행 (scheduled + ondemand)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        default=True,
        help="모든 워커 실행 (기본값)",
    )

    args = parser.parse_args()

    # 개별 옵션이 지정되면 --all은 False
    if args.naver or args.scheduled or args.ondemand or args.google or args.crawl:
        args.all = False

    return args


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args))

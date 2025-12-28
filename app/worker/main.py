"""
통합 크롤링 워커 메인 진입점.

두 가지 워커를 동시에 실행합니다:
- ScheduledCrawlWorker: 스케줄 기반 Instagram 피드 크롤링
- OnDemandCrawlWorker: 온디맨드 (Instagram 개별 + Universal) 크롤링

실행 방법:
    python -m app.worker.main                # 모든 워커 실행
    python -m app.worker.main --scheduled    # 스케줄 워커만
    python -m app.worker.main --ondemand     # 온디맨드 워커만

주요 기능:
    - 두 워커의 동시 실행 및 관리
    - 시그널 핸들링 (SIGINT, SIGTERM)
    - 비동기 로깅 통합
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

# 워커 전용 비동기 로거 설정
logger = AsyncLoggerManager.setup_worker_logger(
    log_prefix="crawl_worker",
    log_dir=Path("logs"),
    level=logging.DEBUG
)
logger.info(f"통합 크롤링 워커 로거 초기화 완료 - 로그 파일: {logger.log_file}")

# 모듈 import
try:
    logger.info("모듈 import 시작...")

    from app.worker.scheduled_worker import ScheduledCrawlWorker
    from app.worker.ondemand_worker import OnDemandCrawlWorker

    # 크롤러 및 워커 관련 로거들이 워커 로거와 같은 핸들러를 사용하도록 설정
    worker_handlers = logger.handlers
    for logger_name in [
        # 크롤러 관련
        'instagram.crawler', 'instagram.crawl_service', 'instagram.post_service', 'universal_crawl',
        # 워커 관련 (누락되어 있던 것들)
        'app.shared.worker.base_worker',
        'app.worker.scheduled_worker',
        'app.worker.ondemand_worker',
        'app.worker.crawl_worker_base',
        'instagram.worker_status',
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


async def run_workers(run_scheduled: bool = True, run_ondemand: bool = True):
    """워커들을 실행합니다.

    Args:
        run_scheduled: 스케줄 워커 실행 여부
        run_ondemand: 온디맨드 워커 실행 여부
    """
    workers = []

    if run_scheduled:
        scheduled_worker = ScheduledCrawlWorker()
        workers.append(("scheduled", scheduled_worker))
        logger.info("ScheduledCrawlWorker 생성됨")

    if run_ondemand:
        ondemand_worker = OnDemandCrawlWorker()
        workers.append(("ondemand", ondemand_worker))
        logger.info("OnDemandCrawlWorker 생성됨")

    if not workers:
        logger.error("실행할 워커가 없습니다.")
        return

    # 시그널 핸들러 설정
    shutdown_event = asyncio.Event()

    def signal_handler(signum, frame):
        logger.info(f"종료 시그널 수신: {signum}")
        shutdown_event.set()
        for name, worker in workers:
            worker.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 워커 태스크 생성
    tasks = []
    for name, worker in workers:
        task = asyncio.create_task(worker.start(), name=f"worker_{name}")
        tasks.append(task)
        logger.info(f"{name} 워커 태스크 시작")

    try:
        # 모든 워커가 완료될 때까지 대기
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        logger.info("워커 태스크 취소됨")
    finally:
        # 정리
        for task in tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


async def main(args):
    """메인 함수."""
    # asyncio 예외 핸들러 설정
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(handle_exception)

    logger.info("=" * 50)
    logger.info("통합 크롤링 워커 프로세스 시작")
    logger.info(f"PID: {os.getpid()}")
    logger.info(f"Python 버전: {sys.version}")
    logger.info(f"실행 모드: scheduled={args.scheduled or args.all}, ondemand={args.ondemand or args.all}")
    logger.info("=" * 50)

    try:
        await run_workers(
            run_scheduled=args.scheduled or args.all,
            run_ondemand=args.ondemand or args.all,
        )
    except Exception as e:
        logger.critical(f"워커 치명적 오류: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("통합 크롤링 워커 프로세스 종료")
        AsyncLoggerManager.shutdown()


def parse_args():
    """명령행 인자 파싱."""
    parser = argparse.ArgumentParser(description="통합 크롤링 워커")
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
        "--all",
        action="store_true",
        default=True,
        help="모든 워커 실행 (기본값)",
    )

    args = parser.parse_args()

    # --scheduled 또는 --ondemand가 지정되면 --all은 False
    if args.scheduled or args.ondemand:
        args.all = False

    return args


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args))

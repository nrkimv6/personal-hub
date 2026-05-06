"""
통합 워커 메인 진입점.

WorkerOrchestrator를 사용하여 모든 워커를 관리합니다:
- NaverMonitorWorker: 네이버 예약 모니터링/스나이핑
- ScheduledCrawlWorker: 스케줄 기반 Instagram 피드 크롤링
- OnDemandCrawlWorker: 온디맨드 (Instagram 개별 + Universal) 크롤링
- GoogleSearchWorker: Google 검색 큐 처리
- VideoDownloadWorker: YouTube/Vimeo 비디오 다운로드 처리 (브라우저 불필요)
- FileSearchWorker: 파일 검색 처리 (ripgrep/Everything, 유저 세션 필요)
- PopupMonitorWorker: 네이버 팝업 URL 모니터링

실행 방법:
    python -m app.worker.main                  # 모든 워커 실행
    python -m app.worker.main --naver          # 네이버 워커만
    python -m app.worker.main --scheduled      # 스케줄 워커만
    python -m app.worker.main --ondemand       # 온디맨드 워커만
    python -m app.worker.main --google         # Google 검색 워커만
    python -m app.worker.main --crawl          # 크롤 워커만 (scheduled + ondemand)
    python -m app.worker.main --video-dl       # 비디오 다운로드 워커만
    python -m app.worker.main --popup          # 네이버 팝업 URL 워커만

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
is_dev = os.environ.get("APP_MODE") == "admin"
log_dir = Path("logs/admin") if is_dev else Path("logs")
log_dir.mkdir(parents=True, exist_ok=True)

# 워커 전용 비동기 로거 설정
logger = AsyncLoggerManager.setup_worker_logger(
    log_prefix="worker",
    log_dir=log_dir,
    level=logging.DEBUG
)
logger.info(f"통합 워커 로거 초기화 완료 - 로그 파일: {logger.log_file}")

from app.core.runtime_fingerprint import get_worker_runtime_fingerprint_snapshot

_worker_runtime_snapshot = get_worker_runtime_fingerprint_snapshot()
logger.info(
    "Worker runtime fingerprint: runtime=%s source=%s started_at=%s files=%s",
    _worker_runtime_snapshot["runtime_fingerprint"],
    _worker_runtime_snapshot["source_fingerprint"],
    _worker_runtime_snapshot.get("captured_at"),
    ",".join(str(item["path"]) for item in _worker_runtime_snapshot["source_files"]),
)

# 모듈 import
try:
    logger.info("모듈 import 시작...")

    from app.worker.orchestrator import WorkerOrchestrator
    from app.worker.naver_monitor_worker import NaverMonitorWorker
    from app.worker.scheduled_worker import ScheduledCrawlWorker
    from app.worker.ondemand_worker import OnDemandCrawlWorker
    from app.worker.google_search_worker import GoogleSearchWorker
    from app.worker.activity_worker import ActivityWorker
    from app.worker.mobile_crawl_worker import MobileCrawlWorker
    from app.worker.video_download_worker import VideoDownloadWorker
    from app.worker.file_search_worker import FileSearchWorker
    from app.worker.plan_archive_listener import PlanArchiveListener
    from app.modules.git_repos.worker import GitRepoWorker
    from app.worker.kakao_monitor_worker import KakaoMonitorWorker
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker
    from app.worker.popup_monitor_worker import PopupMonitorWorker

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
        'app.worker.activity_worker',
        'app.worker.video_download_worker',
        'app.worker.file_search_worker',
        'app.worker.plan_archive_listener',
        'app.worker.coupang_monitor_worker',
        'app.modules.coupang_travel.services.http_client',
        'app.modules.coupang_travel.services.monitor_service',
        'app.modules.coupang_travel.services.api_client',
        'app.worker.crawl_worker_base',
        'app.modules.git_repos.worker',
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
    run_activity: bool = True,
    run_mobile: bool = True,
    run_video_dl: bool = True,
    run_file_search: bool = True,
    run_git: bool = True,
    run_plan_archive_listener: bool = True,
    run_coupang: bool = True,
    run_popup: bool = True,
):
    """WorkerOrchestrator를 사용하여 워커들을 실행합니다.

    Args:
        run_naver: 네이버 워커 실행 여부
        run_scheduled: 스케줄 워커 실행 여부
        run_ondemand: 온디맨드 워커 실행 여부
        run_google: Google 검색 워커 실행 여부
        run_activity: Activity 워커 실행 여부
        run_mobile: Mobile 크롤링 워커 실행 여부
        run_video_dl: 비디오 다운로드 워커 실행 여부
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

        if run_activity:
            activity_worker = ActivityWorker(
                browser_manager=orchestrator.browser_manager
            )
            orchestrator.register_worker("activity", activity_worker)
            logger.info("ActivityWorker 등록됨")

        if run_mobile:
            mobile_worker = MobileCrawlWorker(
                browser_manager=None  # 모바일 서버가 브라우저 관리
            )
            orchestrator.register_worker("mobile_crawl", mobile_worker)
            logger.info("MobileCrawlWorker 등록됨")

        if run_video_dl:
            video_dl_worker = VideoDownloadWorker()
            orchestrator.register_worker("video_dl", video_dl_worker)
            logger.info("VideoDownloadWorker 등록됨")

        if run_file_search:
            file_search_worker = FileSearchWorker()
            orchestrator.register_worker("file_search", file_search_worker)
            logger.info("FileSearchWorker 등록됨")

        if run_git:
            git_worker = GitRepoWorker()
            orchestrator.register_worker("git_repos", git_worker)
            logger.info("GitRepoWorker 등록됨")

        if run_plan_archive_listener:
            plan_archive_listener = PlanArchiveListener()
            orchestrator.register_worker("plan_archive_listener", plan_archive_listener)
            logger.info("PlanArchiveListener 등록됨")

        # 카카오 모니터 워커 (활성 설정 0건이어도 idle 모드로 등록)
        kakao_stage = "import"
        try:
            from app.core.dependencies import get_db_session
            from app.models.kakao_monitor import KakaoWatchConfig
            from app.modules.kakao_monitor.runtime_status import mark_registration

            kakao_stage = "query"
            with get_db_session() as _db:
                active_config_count = _db.query(KakaoWatchConfig).filter(
                    KakaoWatchConfig.is_active.is_(True)
                ).count()

            kakao_stage = "instantiate"
            kakao_worker = KakaoMonitorWorker(
                browser_manager=orchestrator.browser_manager
            )

            kakao_stage = "register"
            orchestrator.register_worker("kakao_monitor", kakao_worker)
            mark_registration(registered=True, stage="register")
            logger.info(
                "[KAKAO_REGISTER] 등록 완료 (active_config_count=%d)",
                active_config_count,
            )
            if active_config_count == 0:
                logger.info(
                    "[KAKAO_REGISTER] active config 없음 - idle 모드로 대기"
                )
        except Exception as _e:
            try:
                from app.modules.kakao_monitor.runtime_status import mark_registration

                mark_registration(
                    registered=False,
                    stage=kakao_stage,
                    error=f"{type(_e).__name__}: {_e}",
                )
            except Exception:
                pass
            logger.warning(
                "[KAKAO_REGISTER] 등록 실패 stage=%s error=%s",
                kakao_stage,
                _e,
            )

        # 쿠팡 모니터 워커
        if run_coupang:
            try:
                coupang_worker = CoupangMonitorWorker(
                    browser_manager=orchestrator.browser_manager
                )
                orchestrator.register_worker("coupang_monitor", coupang_worker)
                logger.info("[COUPANG_REGISTER] CoupangMonitorWorker 등록됨")
            except Exception as _e:
                logger.warning(
                    "[COUPANG_REGISTER] 등록 실패: %s",
                    _e,
                )

        # 네이버 팝업 URL 모니터 워커
        if run_popup:
            try:
                popup_worker = PopupMonitorWorker(
                    browser_manager=orchestrator.browser_manager
                )
                orchestrator.register_worker("popup_monitor", popup_worker)
                logger.info("[POPUP_REGISTER] PopupMonitorWorker 등록됨")
            except Exception as _e:
                logger.warning(
                    "[POPUP_REGISTER] 등록 실패: %s",
                    _e,
                )

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
        f"google={args.google or args.all}, "
        f"activity={args.activity or args.all}, "
        f"mobile={args.mobile or args.all}, "
            f"video_dl={args.video_dl or args.all}, "
            f"git={args.git or args.all}, "
            f"coupang={args.coupang or args.all}, "
            f"popup={args.popup or args.all}"
    )
    logger.info("=" * 50)

    try:
        await run_with_orchestrator(
            run_naver=args.naver or args.all,
            run_scheduled=args.scheduled or args.crawl or args.all,
            run_ondemand=args.ondemand or args.crawl or args.all,
            run_google=args.google or args.all,
            run_activity=args.activity or args.all,
            run_mobile=args.mobile or args.all,
            run_video_dl=args.video_dl or args.all,
            run_file_search=args.file_search or args.all,
            run_git=args.git or args.all,
            run_plan_archive_listener=args.all,
            run_coupang=args.coupang or args.all,
            run_popup=args.popup or args.all,
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
        "--activity",
        action="store_true",
        help="Activity 워커만 실행 (문화/체육센터 강좌)",
    )
    parser.add_argument(
        "--mobile",
        action="store_true",
        help="Mobile 크롤링 워커만 실행",
    )
    parser.add_argument(
        "--video-dl",
        action="store_true",
        dest="video_dl",
        help="비디오 다운로드 워커만 실행 (YouTube/Vimeo)",
    )
    parser.add_argument(
        "--file-search",
        action="store_true",
        dest="file_search",
        help="파일 검색 워커만 실행 (ripgrep/Everything)",
    )
    parser.add_argument(
        "--git",
        action="store_true",
        help="Git 레포 워커만 실행",
    )
    parser.add_argument(
        "--coupang",
        action="store_true",
        help="쿠팡 모니터 워커만 실행",
    )
    parser.add_argument(
        "--popup",
        action="store_true",
        help="네이버 팝업 URL 모니터 워커만 실행",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        default=True,
        help="모든 워커 실행 (기본값)",
    )

    args = parser.parse_args()

    # 개별 옵션이 지정되면 --all은 False
    if args.naver or args.scheduled or args.ondemand or args.google or args.crawl or args.activity or args.mobile or args.video_dl or args.file_search or args.git or args.coupang or args.popup:
        args.all = False

    return args


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args))

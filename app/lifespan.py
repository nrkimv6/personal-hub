"""
FastAPI 애플리케이션 lifespan 관리 모듈.
startup/shutdown 로직과 stale 리소스 정리를 담당합니다.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pathlib import Path
import asyncio
import os
import subprocess

from app.config import settings, logger
from app.database import check_schema_drift, init_extra_tables, sync_serial_sequences


async def cleanup_api_stale_resources():
    """API 시작 시 stale 리소스를 정리합니다.

    NSSM 서비스 환경에서는 워커가 독립적으로 관리되므로
    API는 워커 프로세스나 워커 관련 DB 상태를 건드리지 않습니다.
    워커 상태(worker_status, monitor_schedules)는 워커 자체가 관리합니다.
    """
    try:
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            # LLM 요청 stale processing 정리 (processing 상태로 남은 요청을 failed로)
            from app.modules.claude_worker.services.llm_service import LLMService
            llm_service = LLMService(db)
            stale_count = llm_service.cleanup_stale_processing(timeout_minutes=0)  # 즉시 정리
            if stale_count > 0:
                logger.info(f"앱 시작 시 stale LLM processing 요청 정리: {stale_count}개")

            db.commit()
        finally:
            db.close()

        # 브라우저 프로필 잠금 파일 정리 (API가 브라우저를 사용하는 경우 대비)
        profile_lock = Path("browser_data/browser_profile/lockfile")
        if profile_lock.exists():
            try:
                profile_lock.unlink()
                logger.info("브라우저 프로필 잠금 파일 삭제")
            except Exception as e:
                logger.warning(f"브라우저 프로필 잠금 파일 삭제 실패: {str(e)}")

    except Exception as e:
        logger.error(f"API stale 리소스 정리 중 오류: {str(e)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션의 수명 주기를 관리합니다."""
    # app.state 초기화
    app.state.api_ready = False
    app.state.health_monitor = None
    app.state.health_monitor_task = None
    app.state.system_cache_collector = None
    app.state.system_cache_task = None
    app.state.redis_cleanup_scheduler = None
    app.state.redis_cleanup_task = None

    # 테스트 환경에서는 DB 커넥션 풀 고갈 방지를 위해 lifespan 초기화 스킵
    if os.environ.get("TESTING"):
        logger.info("TESTING 환경: lifespan 초기화 스킵 (DB 커넥션 풀 보호)")
        yield
        return

    # 사망 추적: 시작 기록
    try:
        from app.core.death_log import record_start
        record_start()
    except Exception:
        pass

    logger.info("=" * 60)
    logger.info("API 서버 시작")
    logger.info(f"PID: {os.getpid()}")
    logger.info("=" * 60)

    # 추가 테이블 초기화 (worker_status, booking_stats, booking_settings)
    try:
        init_extra_tables()
        check_schema_drift()
        synced = sync_serial_sequences()
        if synced:
            logger.info(f"SERIAL 시퀀스 동기화: {synced}건")

        # 이미지 분류 모듈 DB 초기화 - 비활성화 (매번 불필요하게 실행됨)
        # from app.modules.image_classifier.database import init_db as init_ic_db
        # init_ic_db()

        # 파일 분류 모듈 DB 초기화
        try:
            from app.modules.file_classifier.database import init_db as fc_init_db
            fc_init_db()
            logger.info("파일 분류 모듈 DB 초기화 완료")
        except Exception as e:
            logger.warning(f"파일 분류 모듈 DB 초기화 실패 (무시됨): {e}")

        # 발표 사진 원근 보정 모듈 DB 초기화
        try:
            from app.modules.slide_scanner.database import init_db as ss_init_db
            ss_init_db()
            logger.info("슬라이드 스캐너 모듈 DB 초기화 완료")
        except Exception as e:
            logger.warning(f"슬라이드 스캐너 모듈 DB 초기화 실패 (무시됨): {e}")

        logger.info("추가 테이블 초기화 완료")
    except Exception as e:
        logger.error(f"추가 테이블 초기화 실패: {str(e)}")
        try:
            from app.services.operational_issue_store import (
                OperationalIssueReporter,
                OperationalIssueSource,
            )

            OperationalIssueReporter.report(
                error=e,
                source=OperationalIssueSource.MIGRATION,
                severity="critical",
                context={
                    "phase": "api_startup",
                    "step": "db_init",
                },
                notify=True,
                persist_error_log=True,
            )
        except Exception:
            pass

    # image_classifier: stale task_progress 정리 (서버 재시작 시 running → failed)
    try:
        from app.modules.image_classifier.database import engine as ic_engine
        import sqlalchemy
        if ic_engine:
            with ic_engine.connect() as conn:
                result = conn.execute(sqlalchemy.text(
                    "UPDATE task_progress SET status = 'failed', "
                    "error_message = 'server restarted', updated_at = datetime('now') "
                    "WHERE status = 'running'"
                ))
                conn.commit()
                if result.rowcount > 0:
                    logger.info(f"image_classifier stale task_progress {result.rowcount}건 정리")
    except Exception as e:
        logger.warning(f"image_classifier stale task_progress 정리 실패: {e}")

    # API stale 리소스 정리 (워커는 독립적으로 관리됨)
    # Session 0에서 hang 방지: 10초 타임아웃
    try:
        await asyncio.wait_for(cleanup_api_stale_resources(), timeout=10)
    except asyncio.TimeoutError:
        logger.warning("API stale 리소스 정리 타임아웃 (10초) — 스킵")
    except Exception as e:
        logger.error(f"API stale 리소스 정리 실패: {str(e)}")

    try:
        logger.info("워커는 Session 1에서 독립 관리됩니다 (startup-browser-workers.ps1)")
        logger.info("워커 명령은 Redis를 통해 전달됩니다 (worker:commands)")

        # 헬스 모니터 시작 (Session 0에서는 비활성화 — subprocess/network hang 방지)
        from app.shared.notification.notification_service import _IN_SESSION_0
        if settings.HEALTH_MONITOR_ENABLED and not _IN_SESSION_0:
            try:
                from app.services.health_monitor_service import HealthMonitorService

                # NotificationService 인스턴스 생성 (알림용)
                try:
                    from app.shared.notification.notification_service import NotificationService as SharedNotificationService
                    notif_service = SharedNotificationService()
                except Exception:
                    notif_service = None

                app.state.health_monitor = HealthMonitorService(notification_service=notif_service)
                app.state.health_monitor_task = asyncio.create_task(app.state.health_monitor.run_monitor_loop())
                logger.info("헬스 모니터 시작됨")
            except Exception as e:
                logger.error(f"헬스 모니터 시작 실패: {str(e)}")

        # 시스템 상태 캐시 수집기 시작
        try:
            from app.modules.system.services.system_cache_collector import SystemCacheCollector

            app.state.system_cache_collector = SystemCacheCollector(interval_seconds=60)
            app.state.system_cache_task = asyncio.create_task(app.state.system_cache_collector.run_collector_loop())
            logger.info("시스템 상태 캐시 수집기 시작됨")
        except Exception as e:
            logger.error(f"시스템 상태 캐시 수집기 시작 실패: {str(e)}")

        # Redis 좀비 연결 정리 스케줄러 시작
        try:
            from app.shared.redis.cleanup_scheduler import RedisCleanupScheduler
            app.state.redis_cleanup_scheduler = RedisCleanupScheduler()
            app.state.redis_cleanup_task = asyncio.create_task(app.state.redis_cleanup_scheduler.run_cleanup_loop())
            logger.info("Redis 좀비 정리 스케줄러 시작됨")
        except Exception as e:
            logger.error(f"Redis 좀비 정리 스케줄러 시작 실패: {str(e)}")

    except Exception as e:
        logger.error(f"애플리케이션 시작 중 오류 발생: {str(e)}", exc_info=True)

    # Redis 좀비 연결 정리 (이전 프로세스의 잔여 pubsub 구독)
    try:
        import redis as _redis_sync
        _r = _redis_sync.Redis(host="localhost", port=6379, decode_responses=True, socket_connect_timeout=3)
        _r.ping()
        _clients = _r.client_list()
        _zombies = [c for c in _clients if int(c.get("idle", 0)) > 60 and ("S" in c.get("flags", "") or c.get("cmd") in ("subscribe", "psubscribe"))]
        if _zombies:
            for _z in _zombies:
                try:
                    _r.client_kill_filter(_id=int(_z["id"]))
                except Exception:
                    pass
            logger.info(f"Redis 좀비 연결 {len(_zombies)}개 정리 완료 (startup)")
        _r.close()
    except Exception as e:
        logger.debug(f"Redis 좀비 정리 스킵: {e}")

    app.state.api_ready = True
    logger.info("API startup 완료 — ready 상태")

    yield

    # 종료 시 실행
    app.state.api_ready = False
    logger.info("API 서버 종료 중...")

    # Redis 좀비 연결 정리 (graceful shutdown)
    try:
        import redis as _redis_sync
        _r = _redis_sync.Redis(host="localhost", port=6379, decode_responses=True, socket_connect_timeout=3)
        _r.ping()
        _clients = _r.client_list()
        _zombies = [c for c in _clients if int(c.get("idle", 0)) > 60 and ("S" in c.get("flags", "") or c.get("cmd") in ("subscribe", "psubscribe"))]
        if _zombies:
            for _z in _zombies:
                try:
                    _r.client_kill_filter(_id=int(_z["id"]))
                except Exception:
                    pass
            logger.info(f"Redis 좀비 연결 {len(_zombies)}개 정리 완료 (shutdown)")
        _r.close()
    except Exception:
        pass

    # 사망 추적: lifespan shutdown (정상 종료) 기록
    # atexit의 _death_logger()도 호출되지만 여기서 먼저 더 상세히 기록
    try:
        from app.core.death_log import record_death
        record_death(cause="normal_shutdown", details="lifespan shutdown (uvicorn graceful exit)")
    except Exception:
        pass

    # dev-runner 프로세스 종료
    try:
        from app.modules.dev_runner.services.state import get_state
        dev_runner_state = get_state()
        if dev_runner_state.is_running():
            logger.info("dev-runner 프로세스 종료 중...")
            dev_runner_state.process.terminate()
            try:
                dev_runner_state.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                dev_runner_state.process.kill()
                dev_runner_state.process.wait()
            logger.info("dev-runner 프로세스 종료 완료")
    except Exception as e:
        logger.error(f"dev-runner 프로세스 종료 실패: {str(e)}")

    # 헬스 모니터 태스크 취소 및 세션 정리
    if app.state.health_monitor_task:
        app.state.health_monitor_task.cancel()
        try:
            await asyncio.wait_for(app.state.health_monitor_task, timeout=5)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    if app.state.health_monitor:
        try:
            await app.state.health_monitor.close()
        except Exception:
            pass
        logger.info("헬스 모니터 종료됨")

    # 시스템 캐시 수집기 태스크 취소
    if app.state.system_cache_task:
        app.state.system_cache_task.cancel()
        try:
            await asyncio.wait_for(app.state.system_cache_task, timeout=5)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        logger.info("시스템 상태 캐시 수집기 종료됨")

    # Redis 좀비 정리 스케줄러 태스크 취소
    if app.state.redis_cleanup_task:
        app.state.redis_cleanup_task.cancel()
        try:
            await asyncio.wait_for(app.state.redis_cleanup_task, timeout=5)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        logger.info("Redis 좀비 정리 스케줄러 종료됨")

    logger.info("API 서버 종료 완료")

"""
Claude Code LLM 분류 워커 프로세스

API 서버와 분리되어 독립적으로 LLM 분류 작업을 수행합니다.

실행 방법:
    python -m app.worker.claude_worker

주요 기능:
    - Pending LLM 분류 요청 처리 (InstagramLLMClassificationRequest)
    - Claude CLI subprocess 실행
    - 결과 파싱 및 저장
"""
import asyncio
import sys
import os
import signal
import logging
import uuid
from datetime import datetime
from pathlib import Path

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 비동기 로거 설정
from app.utils.async_logger import AsyncLoggerManager

# 워커 전용 비동기 로거 설정
logger = AsyncLoggerManager.setup_worker_logger(
    log_prefix="claude_worker",
    log_dir=Path("logs"),
    level=logging.DEBUG
)
logger.info(f"Claude 워커 비동기 로거 초기화 완료 - 로그 파일: {logger.log_file}")

# 모듈 import
try:
    logger.info("모듈 import 시작...")

    from app.database import SessionLocal
    logger.debug("app.database import 완료")

    from app.models import InstagramPost
    from app.models.instagram_llm_request import InstagramLLMClassificationRequest
    logger.debug("app.models import 완료")

    from app.modules.instagram.services.llm_classifier_service import LLMClassifierService
    logger.debug("llm_classifier_service import 완료")

    # LLM 관련 로거가 워커 로거와 같은 핸들러를 사용하도록 설정
    worker_handlers = logger.handlers
    for logger_name in ['instagram.llm_classifier']:
        sub_logger = logging.getLogger(logger_name)
        sub_logger.setLevel(logging.DEBUG)
        for handler in worker_handlers:
            sub_logger.addHandler(handler)
        sub_logger.propagate = False
    logger.debug("LLM 서브 로거 설정 완료")

    logger.info("모든 모듈 import 완료")

except Exception as e:
    import traceback
    logger.critical(f"모듈 import 중 치명적 오류: {e}")
    logger.critical(f"Traceback:\n{traceback.format_exc()}")
    AsyncLoggerManager.shutdown()
    sys.exit(1)


class ClaudeWorker:
    """Claude Code LLM 분류 워커."""

    def __init__(self):
        self.shutdown_event = asyncio.Event()
        self.check_interval = 10  # 10초마다 체크
        self.pid = os.getpid()
        self.start_time: datetime = None
        self.worker_id: str = None

    async def start(self):
        """워커 시작."""
        logger.info(f"Claude 워커 시작 (PID: {self.pid})")
        self.start_time = datetime.now()

        # 워커 상태 등록
        self._register_worker_status()

        try:
            await self._main_loop()
        finally:
            await self._cleanup()

    def _register_worker_status(self):
        """워커 상태를 DB에 등록합니다."""
        db = SessionLocal()
        try:
            service = LLMClassifierService(db)
            self.worker_id = str(uuid.uuid4())
            service.register_worker(self.worker_id, self.pid)
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
            service = LLMClassifierService(db)
            service.update_heartbeat(self.worker_id)
        except Exception as e:
            logger.warning(f"Heartbeat 업데이트 실패: {e}")
        finally:
            db.close()

    def _update_worker_state(self, state: str, request_id: int = None):
        """워커 상태를 업데이트합니다."""
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = LLMClassifierService(db)
            service.update_worker_state(self.worker_id, state, request_id)
        except Exception as e:
            logger.warning(f"워커 상태 업데이트 실패: {e}")
        finally:
            db.close()

    def _increment_processed(self):
        """처리 카운트 증가."""
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = LLMClassifierService(db)
            service.increment_processed(self.worker_id)
        except Exception as e:
            logger.warning(f"처리 카운트 증가 실패: {e}")
        finally:
            db.close()

    def _increment_error(self):
        """에러 카운트 증가."""
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = LLMClassifierService(db)
            service.increment_error(self.worker_id)
        except Exception as e:
            logger.warning(f"에러 카운트 증가 실패: {e}")
        finally:
            db.close()

    def _mark_worker_dead(self):
        """워커를 종료 상태로 표시합니다."""
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = LLMClassifierService(db)
            service.mark_worker_dead(self.worker_id)
            logger.info(f"워커 종료 상태 표시 완료: worker_id={self.worker_id}")
        except Exception as e:
            logger.error(f"워커 종료 상태 표시 실패: {e}")
        finally:
            db.close()

    async def stop(self):
        """워커 종료."""
        logger.info("Claude 워커 종료 요청")
        self.shutdown_event.set()

    async def _cleanup(self):
        """정리."""
        logger.info("Claude 워커 정리 시작")

        # 워커 상태를 종료로 표시
        self._mark_worker_dead()

        logger.info("Claude 워커 정리 완료")
        AsyncLoggerManager.shutdown()

    async def _main_loop(self):
        """메인 루프."""
        logger.info(f"메인 루프 시작 (체크 간격: {self.check_interval}초)")

        while not self.shutdown_event.is_set():
            try:
                # Heartbeat 업데이트
                self._update_heartbeat()

                # Pending 요청 처리
                await self._process_pending_requests()

                # 대기
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
            service = LLMClassifierService(db)
            request = service.get_pending_request()

            if request:
                logger.info(f"Pending 요청 발견: id={request.id}, post_id={request.post_id}")
                await self._execute_classification(request, db, service)

        except Exception as e:
            logger.error(f"Pending 요청 처리 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _execute_classification(
        self,
        request: InstagramLLMClassificationRequest,
        db,
        service: LLMClassifierService,
    ):
        """LLM 분류 실행."""
        try:
            # 처리 중으로 변경
            service.mark_processing(request.id)
            self._update_worker_state("processing", request.id)

            # 게시물 조회
            post = db.query(InstagramPost).filter(InstagramPost.id == request.post_id).first()
            if not post:
                service.mark_failed(request.id, "게시물을 찾을 수 없음")
                self._increment_error()
                logger.warning(f"게시물 없음: post_id={request.post_id}")
                return

            if not post.caption:
                service.mark_failed(request.id, "게시물에 caption 없음")
                self._increment_error()
                logger.warning(f"caption 없음: post_id={request.post_id}")
                return

            logger.info(f"LLM 분류 시작: post_id={request.post_id}, caption 길이={len(post.caption)}")

            # Claude CLI 실행 (비동기 실행을 위해 run_in_executor 사용)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: service.execute_claude_classification(post.caption)
            )

            if result["success"]:
                parsed = result["result"]
                confidence = parsed.get("confidence", 0.5)

                service.mark_completed(
                    request.id,
                    parsed,
                    confidence,
                    result.get("prompt", ""),
                    result.get("raw_response", ""),
                )
                self._increment_processed()
                logger.info(
                    f"LLM 분류 완료: post_id={request.post_id}, "
                    f"is_event={parsed.get('is_event', True)}, confidence={confidence}"
                )
            else:
                service.mark_failed(request.id, result["error"])
                self._increment_error()
                logger.warning(f"LLM 분류 실패: {result['error']}")

        except Exception as e:
            service.mark_failed(request.id, str(e))
            self._increment_error()
            logger.error(f"LLM 분류 예외: {e}", exc_info=True)
        finally:
            # 워커 상태를 idle로 복원
            self._update_worker_state("idle")


# 전역 워커 인스턴스
worker_instance: ClaudeWorker = None


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
    logger.info("Claude Code LLM 분류 워커 프로세스 시작")
    logger.info(f"PID: {os.getpid()}")
    logger.info(f"Python 버전: {sys.version}")
    logger.info("=" * 50)

    worker_instance = ClaudeWorker()

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
        logger.info("Claude 워커 프로세스 종료")


if __name__ == "__main__":
    asyncio.run(main())

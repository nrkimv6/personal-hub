"""
Claude LLM 워커 프로세스

API 서버와 분리되어 독립적으로 LLM 작업을 수행합니다.

실행 방법:
    python -m app.modules.claude_worker.worker.worker

주요 기능:
    - Pending LLM 요청 처리
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
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# 비동기 로거 설정
from app.utils.async_logger import AsyncLoggerManager

# 워커 전용 비동기 로거 설정
logger = AsyncLoggerManager.setup_worker_logger(
    log_prefix="llm_worker",
    log_dir=Path("logs"),
    level=logging.DEBUG
)
logger.info(f"LLM 워커 비동기 로거 초기화 완료 - 로그 파일: {logger.log_file}")

# 모듈 import
try:
    logger.info("모듈 import 시작...")

    from app.database import SessionLocal
    logger.debug("app.database import 완료")

    from app.modules.claude_worker.models.llm_request import LLMRequest
    logger.debug("llm_request 모델 import 완료")

    from app.modules.claude_worker.services.llm_service import LLMService
    logger.debug("llm_service import 완료")

    logger.info("모든 모듈 import 완료")

except Exception as e:
    import traceback
    logger.critical(f"모듈 import 중 치명적 오류: {e}")
    logger.critical(f"Traceback:\n{traceback.format_exc()}")
    AsyncLoggerManager.shutdown()
    sys.exit(1)


class LLMWorker:
    """Claude LLM 워커."""

    def __init__(self):
        self.shutdown_event = asyncio.Event()
        self.check_interval = 10  # 10초마다 체크
        self.pid = os.getpid()
        self.start_time: datetime = None
        self.worker_id: str = None

    async def start(self):
        """워커 시작."""
        logger.info(f"LLM 워커 시작 (PID: {self.pid})")
        self.start_time = datetime.now()

        # 워커 상태 등록
        self._register_worker_status()

        try:
            await self._main_loop()
        finally:
            await self._cleanup()

    def _register_worker_status(self):
        """워커 상태를 DB에 등록."""
        db = SessionLocal()
        try:
            service = LLMService(db)
            self.worker_id = str(uuid.uuid4())
            service.register_worker(self.worker_id, self.pid)
            logger.info(f"워커 상태 등록 완료: worker_id={self.worker_id}")
        except Exception as e:
            logger.error(f"워커 상태 등록 실패: {e}")
        finally:
            db.close()

    def _update_heartbeat(self):
        """하트비트 업데이트."""
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = LLMService(db)
            service.update_heartbeat(self.worker_id)
        except Exception as e:
            logger.warning(f"Heartbeat 업데이트 실패: {e}")
        finally:
            db.close()

    def _update_worker_state(self, state: str, request_id: int = None):
        """워커 상태 업데이트."""
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = LLMService(db)
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
            service = LLMService(db)
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
            service = LLMService(db)
            service.increment_error(self.worker_id)
        except Exception as e:
            logger.warning(f"에러 카운트 증가 실패: {e}")
        finally:
            db.close()

    def _mark_worker_dead(self):
        """워커를 종료 상태로 표시."""
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = LLMService(db)
            service.mark_worker_dead(self.worker_id)
            logger.info(f"워커 종료 상태 표시 완료: worker_id={self.worker_id}")
        except Exception as e:
            logger.error(f"워커 종료 상태 표시 실패: {e}")
        finally:
            db.close()

    async def stop(self):
        """워커 종료."""
        logger.info("LLM 워커 종료 요청")
        self.shutdown_event.set()

    async def _cleanup(self):
        """정리."""
        logger.info("LLM 워커 정리 시작")
        self._mark_worker_dead()
        logger.info("LLM 워커 정리 완료")
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
                    pass

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
            service = LLMService(db)
            request = service.get_pending_request()

            if request:
                logger.info(f"Pending 요청 발견: id={request.id}, caller={request.caller_type}:{request.caller_id}")
                await self._execute_request(request, db, service)

        except Exception as e:
            logger.error(f"Pending 요청 처리 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _execute_request(
        self,
        request: LLMRequest,
        db,
        service: LLMService,
    ):
        """LLM 요청 실행."""
        try:
            # 처리 중으로 변경
            service.mark_processing(request.id)
            self._update_worker_state("processing", request.id)

            logger.info(f"LLM 실행 시작: id={request.id}")

            # Claude CLI 실행 (비동기 실행을 위해 run_in_executor 사용)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: service.execute_claude(request.prompt)
            )

            if result["success"]:
                service.mark_completed(
                    request.id,
                    result["result"],
                    result.get("raw_response", ""),
                )
                self._increment_processed()
                logger.info(f"LLM 실행 완료: id={request.id}")
            else:
                service.mark_failed(request.id, result["error"])
                self._increment_error()
                logger.warning(f"LLM 실행 실패: {result['error']}")

        except Exception as e:
            service.mark_failed(request.id, str(e))
            self._increment_error()
            logger.error(f"LLM 실행 예외: {e}", exc_info=True)
        finally:
            self._update_worker_state("idle")


# 전역 워커 인스턴스
worker_instance: LLMWorker = None


def handle_exception(loop, context):
    """asyncio 예외 핸들러."""
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

    loop = asyncio.get_running_loop()
    loop.set_exception_handler(handle_exception)

    logger.info("=" * 50)
    logger.info("Claude LLM 워커 프로세스 시작")
    logger.info(f"PID: {os.getpid()}")
    logger.info(f"Python 버전: {sys.version}")
    logger.info("=" * 50)

    worker_instance = LLMWorker()

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
        logger.info("LLM 워커 프로세스 종료")


if __name__ == "__main__":
    asyncio.run(main())

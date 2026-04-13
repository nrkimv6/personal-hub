"""
프록시 사용 이력 로거
작성일: 2025-12-18

특징:
- 모니터링 로직과 완전 분리
- Fire-and-forget 방식 (실패해도 메인 로직 영향 없음)
- 메모리 버퍼링 + 배치 쓰기
- 종료 시 플러시 보장
"""

import asyncio
import logging
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)


@dataclass
class ProxyAttempt:
    """단일 프록시 시도 정보"""
    proxy_url: str
    proxy_host: str
    attempt_number: int
    success: bool = False
    http_status: Optional[int] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    response_time_ms: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)


class ProxyUsageLogger:
    """
    프록시 사용 이력 로거

    사용법:
        logger = ProxyUsageLogger()
        await logger.start()

        # 요청 시작
        request_id = logger.start_request(schedule_id, target_url, fetch_method)

        # 각 시도 기록 (논블로킹, fire-and-forget)
        logger.log_attempt(request_id, proxy_url, success=False, error_type="timeout")
        logger.log_attempt(request_id, proxy_url2, success=True, response_time_ms=500)

        # 요청 완료 (선택적 - 미호출 시 자동 플러시)
        logger.complete_request(request_id, monitoring_event_id=123)

        await logger.stop()
    """

    def __init__(
        self,
        buffer_size: int = 50,
        auto_flush_interval: float = 5.0,
    ):
        self.buffer_size = buffer_size
        self.auto_flush_interval = auto_flush_interval

        # 진행 중인 요청 버퍼 (request_id -> 시도 목록)
        self._pending_requests: Dict[str, dict] = {}

        # 플러시 대기 버퍼
        self._buffer: List[dict] = []
        self._buffer_lock = asyncio.Lock()

        # 자동 플러시 태스크
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """로거 시작 (자동 플러시 활성화)"""
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(self._auto_flush_loop())
        logger.info("ProxyUsageLogger started")

    async def stop(self):
        """로거 종료 (버퍼 플러시)"""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # 남은 버퍼 플러시
        await self._flush_buffer()

        # pending 요청도 모두 플러시
        for request_id in list(self._pending_requests.keys()):
            self._finalize_request(request_id)
        await self._flush_buffer()

        logger.info("ProxyUsageLogger stopped")

    def _sync_flush_on_exit(self):
        """
        동기 종료 핸들러 (atexit, signal handler용)

        비정상 종료 시에도 최대한 버퍼를 저장합니다.
        """
        if not self._buffer and not self._pending_requests:
            return

        logger.info(f"Emergency flush: {len(self._buffer)} buffered, {len(self._pending_requests)} pending")

        # pending 요청 완료 처리
        for request_id in list(self._pending_requests.keys()):
            self._finalize_request(request_id)

        # 동기적으로 직접 DB 쓰기 (별도 스레드 대기 없이)
        if self._buffer:
            try:
                self._batch_insert_logs(self._buffer)
                self._buffer.clear()
            except Exception as e:
                logger.error(f"Emergency flush failed: {e}")

    def start_request(
        self,
        schedule_id: int,
        target_url: str,
        fetch_method: str,
        http_method: Optional[str] = "get",
    ) -> str:
        """
        새 요청 시작 (request_id 반환)

        Args:
            schedule_id: 모니터 스케줄 ID
            target_url: 요청 대상 URL
            fetch_method: 요청 방식 (graphql_api, anonymous_api, etc.)
            http_method: 실제 HTTP 메서드 (get/post)

        Returns:
            request_id: 요청 식별자 (재시도 그룹핑용)
        """
        request_id = str(uuid.uuid4())
        self._pending_requests[request_id] = {
            "schedule_id": schedule_id,
            "target_url": target_url,
            "fetch_method": fetch_method,
            "http_method": (http_method or "get").strip().lower(),
            "started_at": datetime.now(),
            "attempts": [],
        }
        return request_id

    def log_attempt(
        self,
        request_id: str,
        proxy_url: str,
        success: bool = False,
        http_status: Optional[int] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        response_time_ms: Optional[int] = None,
    ) -> None:
        """
        프록시 시도 기록 (논블로킹, fire-and-forget)

        이 메서드는 절대 예외를 발생시키지 않습니다.
        실패해도 메인 로직에 영향 없음.
        """
        try:
            if request_id not in self._pending_requests:
                logger.warning(f"Unknown request_id: {request_id}")
                return

            request = self._pending_requests[request_id]
            attempt_number = len(request["attempts"]) + 1

            # 프록시 호스트 추출
            proxy_host = self._extract_host(proxy_url)

            attempt = ProxyAttempt(
                proxy_url=proxy_url,
                proxy_host=proxy_host,
                attempt_number=attempt_number,
                success=success,
                http_status=http_status,
                error_type=error_type,
                error_message=error_message[:500] if error_message else None,
                response_time_ms=response_time_ms,
            )
            request["attempts"].append(attempt)

            # 성공 시 바로 완료 처리
            if success:
                self._finalize_request(request_id)

        except Exception as e:
            # 절대 예외 전파 안함
            logger.error(f"Failed to log proxy attempt: {e}", exc_info=True)

    def complete_request(
        self,
        request_id: str,
        monitoring_event_id: Optional[int] = None,
    ) -> None:
        """
        요청 완료 처리 (선택적 호출)

        Args:
            request_id: 요청 식별자
            monitoring_event_id: 연결할 모니터링 이벤트 ID
        """
        try:
            if request_id in self._pending_requests:
                self._pending_requests[request_id]["monitoring_event_id"] = monitoring_event_id
                self._finalize_request(request_id)
        except Exception as e:
            logger.error(f"Failed to complete request: {e}", exc_info=True)

    def _finalize_request(self, request_id: str) -> None:
        """요청 완료 후 버퍼로 이동"""
        if request_id not in self._pending_requests:
            return

        request = self._pending_requests.pop(request_id)

        # 각 시도를 버퍼에 추가
        for attempt in request["attempts"]:
            log_entry = {
                "schedule_id": request["schedule_id"],
                "target_url": request["target_url"],
                "fetch_method": request["fetch_method"],
                "http_method": request.get("http_method", "get"),
                "request_id": request_id,
                "monitoring_event_id": request.get("monitoring_event_id"),
                "proxy_url": attempt.proxy_url,
                "proxy_host": attempt.proxy_host,
                "attempt_number": attempt.attempt_number,
                "success": attempt.success,
                "http_status": attempt.http_status,
                "error_type": attempt.error_type,
                "error_message": attempt.error_message,
                "response_time_ms": attempt.response_time_ms,
                "timestamp": attempt.timestamp,
            }
            self._buffer.append(log_entry)

        # 버퍼 크기 체크 후 플러시
        if len(self._buffer) >= self.buffer_size:
            # 비동기로 플러시 스케줄
            asyncio.create_task(self._flush_buffer())

    async def _auto_flush_loop(self):
        """주기적 자동 플러시"""
        while self._running:
            try:
                await asyncio.sleep(self.auto_flush_interval)
                await self._flush_buffer()

                # 오래된 pending 요청 정리 (60초 이상)
                self._cleanup_stale_requests()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Auto flush error: {e}", exc_info=True)

    async def _flush_buffer(self):
        """버퍼를 DB에 기록"""
        async with self._buffer_lock:
            if not self._buffer:
                return

            # 버퍼 복사 후 초기화
            entries = self._buffer.copy()
            self._buffer.clear()

        # 별도 스레드에서 배치 쓰기 실행
        try:
            await asyncio.to_thread(self._batch_insert_logs, entries)
            logger.debug(f"Flushed {len(entries)} proxy usage logs to DB")
        except Exception as e:
            logger.error(f"Failed to flush proxy usage logs: {e}")

    def _batch_insert_logs(self, entries: List[dict]) -> None:
        """
        배치 INSERT (동기, 별도 스레드에서 실행됨)
        """
        from app.database import SessionLocal
        from app.models.proxy_usage import ProxyUsageLog

        session = SessionLocal()
        try:
            logs = [
                ProxyUsageLog(
                    schedule_id=entry["schedule_id"],
                    monitoring_event_id=entry.get("monitoring_event_id"),
                    proxy_url=entry["proxy_url"],
                    proxy_host=entry["proxy_host"],
                    request_id=entry["request_id"],
                    attempt_number=entry["attempt_number"],
                    success=1 if entry["success"] else 0,
                    http_status=entry.get("http_status"),
                    error_type=entry.get("error_type"),
                    error_message=entry.get("error_message"),
                    response_time_ms=entry.get("response_time_ms"),
                    target_url=entry.get("target_url"),
                    fetch_method=entry.get("fetch_method"),
                    http_method=entry.get("http_method"),
                    timestamp=entry["timestamp"],
                )
                for entry in entries
            ]
            session.add_all(logs)
            session.commit()
            logger.debug(f"Inserted {len(logs)} proxy usage logs")
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to insert proxy usage logs: {e}", exc_info=True)
            raise
        finally:
            session.close()

    def _cleanup_stale_requests(self, max_age_seconds: int = 60):
        """오래된 pending 요청 정리"""
        now = datetime.now()
        stale_ids = [
            rid for rid, req in self._pending_requests.items()
            if (now - req["started_at"]).total_seconds() > max_age_seconds
        ]
        for rid in stale_ids:
            logger.warning(f"Cleaning up stale request: {rid}")
            self._finalize_request(rid)

    @staticmethod
    def _extract_host(proxy_url: str) -> str:
        """프록시 URL에서 호스트 추출"""
        try:
            # http://user:pass@host:port -> host
            url = proxy_url.replace("http://", "").replace("https://", "").replace("socks5://", "")
            if "@" in url:
                url = url.split("@")[1]
            return url.split(":")[0]
        except Exception:
            return proxy_url

    # === 편의 메서드 ===

    def get_pending_count(self) -> int:
        """진행 중인 요청 수"""
        return len(self._pending_requests)

    def get_buffer_count(self) -> int:
        """버퍼에 대기 중인 로그 수"""
        return len(self._buffer)


# 싱글톤 인스턴스 (선택적 사용)
_logger_instance: Optional[ProxyUsageLogger] = None


def get_proxy_usage_logger() -> ProxyUsageLogger:
    """싱글톤 ProxyUsageLogger 인스턴스 반환"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = ProxyUsageLogger()
    return _logger_instance


async def init_proxy_usage_logger() -> ProxyUsageLogger:
    """ProxyUsageLogger 초기화 및 시작"""
    logger_instance = get_proxy_usage_logger()
    await logger_instance.start()
    return logger_instance


async def shutdown_proxy_usage_logger():
    """ProxyUsageLogger 종료"""
    global _logger_instance
    if _logger_instance:
        await _logger_instance.stop()
        _logger_instance = None

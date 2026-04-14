"""
파일 검색 워커 (FileSearchWorker).

API(Session 0)에서 Redis 큐에 적재된 파일 검색 요청을 처리합니다.
유저 세션에서 실행되어 ripgrep/Everything을 정상 호출할 수 있습니다.

실행 방법:
    WorkerOrchestrator에서 등록하여 실행
    (app/worker/main.py 참조)

주요 기능:
    - Redis 큐(file_search:requests)에서 검색 요청 수신
    - ripgrep / Everything 실행 → 결과를 DB에 저장
    - Redis 큐(file_search:open)에서 파일 열기 요청 처리
    - 도구 상태 체크: 워커 시작 시 1회 + 검색 요청 시 온디맨드 (30초 경과 시)
    - Redis 미연결 시 DB 폴링 fallback (5초 간격)
    - 시작 시 stale 요청(10분 이상 pending/processing) → failed 처리

Redis 큐 지원:
    - Redis 연결 시: Redis 큐에서 즉시 수신 (0.1초 루프)
    - Redis 미연결 시: SQLite 폴링 fallback (1초 간격)
"""
import asyncio
import json
import logging
import os
import subprocess
import time
from datetime import datetime, timedelta
from typing import Optional

from app.shared.worker.base_worker import BaseWorker
from app.database import SessionLocal
from app.models.file_search_request import FileSearchRequest
from app.models.file_search_status import FileSearchStatus
from app.shared.redis import RedisClient, RedisQueue
from app.shared.redis.queue import FILE_SEARCH_QUEUE, FILE_SEARCH_OPEN_QUEUE

logger = logging.getLogger(__name__)

# 상태 체크 간격 (초)
STATUS_CHECK_INTERVAL = 30
# DB 폴링 간격 (초) — Redis fallback 모드에서 사용
DB_POLL_INTERVAL = 5
# stale 요청 임계값 (분)
STALE_THRESHOLD_MINUTES = 10


class FileSearchWorker(BaseWorker):
    """파일 검색 워커 — 유저 세션에서 실행.

    브라우저가 필요 없으므로 BaseWorker 직접 상속.

    Attributes:
        use_redis: Redis 큐 사용 여부
        redis_queue: 검색 요청 큐
        open_queue: 파일 열기 요청 큐 (fire-and-forget)
        _redis_initialized: Redis 초기화 완료 여부
        _last_status_check: 마지막 상태 체크 타임스탬프
        _last_db_poll: 마지막 DB 폴링 타임스탬프 (fallback 모드)
    """

    def __init__(self):
        """FileSearchWorker 초기화."""
        super().__init__(name="file_search_worker")

        # Redis 큐 관련
        self.use_redis = False
        self.redis_queue: Optional[RedisQueue] = None
        self.open_queue: Optional[RedisQueue] = None
        self._redis_initialized = False

        # 상태 체크 타이밍
        self._last_status_check: float = 0.0
        self._last_db_poll: float = 0.0

    async def _setup_redis(self):
        """Redis 큐 초기화."""
        if self._redis_initialized:
            return

        redis_client = await RedisClient.get_client()
        if redis_client:
            self.redis_queue = RedisQueue(redis_client, FILE_SEARCH_QUEUE)
            self.open_queue = RedisQueue(redis_client, FILE_SEARCH_OPEN_QUEUE)
            self.use_redis = True
            logger.info(f"[{self.name}] Redis 큐 모드 활성화")
        else:
            self.use_redis = False
            logger.info(f"[{self.name}] SQLite 폴링 모드 (Redis 미연결)")

        self._redis_initialized = True

    def _get_loop_interval(self) -> float:
        """메인 루프 간격 반환.

        Returns:
            float: Redis 모드 0.1초, SQLite 모드 1.0초
        """
        return 0.1 if self.use_redis else 1.0

    async def _initialize(self):
        """워커 초기화 — stale 요청 정리 + 도구 상태 1회 체크."""
        await self._cleanup_stale_requests()
        await self._safe_execute("check_tool_status", self._check_tool_status)
        self._last_status_check = time.time()

    async def _main_loop_iteration(self):
        """메인 루프 한 사이클.

        1. Redis 초기화 (최초 1회)
        2. 검색 요청 처리 (Redis 또는 DB 폴링)
        3. 파일 열기 요청 처리
        """
        # Redis 초기화 (첫 번째 호출 시)
        await self._setup_redis()

        # 검색 요청 처리
        if self.use_redis:
            await self._safe_execute("process_redis_queue", self._process_redis_queue)
            await self._safe_execute("process_open_queue", self._process_open_queue)
        else:
            # SQLite 폴링 fallback — 매 루프가 아닌 DB_POLL_INTERVAL 간격으로
            now = time.time()
            if now - self._last_db_poll >= DB_POLL_INTERVAL:
                await self._safe_execute("process_db_pending", self._process_db_pending)
                self._last_db_poll = now

    # ========== Redis 큐 처리 ==========

    async def _process_redis_queue(self):
        """Redis 검색 요청 큐에서 작업을 가져와 처리."""
        if not self.redis_queue:
            return

        job = await self.redis_queue.pop_nowait()
        if not job:
            return  # 큐 비어있음

        search_id = job.get("search_id")
        if not search_id:
            logger.warning(f"[{self.name}] Redis 메시지에 search_id 없음: {job}")
            return

        db = SessionLocal()
        try:
            req = db.query(FileSearchRequest).filter_by(search_id=search_id).first()
            if not req:
                logger.warning(f"[{self.name}] Redis 큐의 요청이 DB에 없음: search_id={search_id}")
                return

            if req.status not in (FileSearchRequest.STATUS_QUEUED, FileSearchRequest.STATUS_PENDING):
                logger.debug(f"[{self.name}] 이미 처리된 요청: search_id={search_id}, status={req.status}")
                return

            await self._execute_search(req, db)
        except Exception as e:
            self._log_worker_error("Redis 큐 처리", e)
        finally:
            db.close()

    async def _process_open_queue(self):
        """Redis 파일 열기 큐에서 작업을 가져와 처리 (fire-and-forget)."""
        if not self.open_queue:
            return

        job = await self.open_queue.pop_nowait()
        if not job:
            return

        file_path = job.get("file_path")
        line_number = job.get("line_number")

        if not file_path:
            logger.warning(f"[{self.name}] open 큐 메시지에 file_path 없음: {job}")
            return

        self._open_file(file_path, line_number)

    # ========== DB 폴링 fallback ==========

    async def _process_db_pending(self):
        """DB에서 pending 상태 요청을 조회하여 처리 (Redis fallback)."""
        db = SessionLocal()
        try:
            req = (
                db.query(FileSearchRequest)
                .filter(FileSearchRequest.status == FileSearchRequest.STATUS_PENDING)
                .order_by(FileSearchRequest.created_at)
                .first()
            )

            if not req:
                return

            logger.info(f"[{self.name}] DB 폴링: 검색 요청 처리 search_id={req.search_id}")
            await self._execute_search(req, db)

        except Exception as e:
            self._log_worker_error("DB 폴링", e)
        finally:
            db.close()

    # ========== 검색 실행 ==========

    async def _execute_search(self, req: FileSearchRequest, db):
        """검색 요청 실행.

        DB status를 processing으로 변경 → SearchService.search() 실행 →
        결과를 result_json에 저장 → status=completed 또는 failed.

        도구 상태가 30초 이상 지났으면 체크 후 갱신.

        Args:
            req: FileSearchRequest DB 모델 인스턴스
            db: DB 세션
        """
        from app.modules.file_search.schemas import SearchRequest
        from app.modules.file_search.services.search_service import SearchService

        # 온디맨드 도구 상태 체크 (마지막 체크로부터 STATUS_CHECK_INTERVAL 경과 시)
        now = time.time()
        if now - self._last_status_check >= STATUS_CHECK_INTERVAL:
            await self._safe_execute("check_tool_status", self._check_tool_status)
            self._last_status_check = time.time()

        logger.info(f"[{self.name}] 검색 시작: search_id={req.search_id}")

        # processing 상태로 변경
        req.mark_processing()
        db.commit()

        start_ms = int(time.time() * 1000)

        try:
            # request_json 역직렬화
            request_data = json.loads(req.request_json)
            search_request = SearchRequest(**request_data)

            # 검색 실행 (DB ignore 패턴 병합을 위해 db 세션 전달)
            service = SearchService()
            result = await service.search(search_request, db=db)

            elapsed_ms = int(time.time() * 1000) - start_ms

            # 결과 저장
            result_json = result.model_dump_json()
            req.mark_completed(result_json=result_json, search_time_ms=elapsed_ms)
            db.commit()

            logger.info(
                f"[{self.name}] 검색 완료: search_id={req.search_id}, "
                f"results={result.total_count}, elapsed={elapsed_ms}ms"
            )

        except Exception as e:
            elapsed_ms = int(time.time() * 1000) - start_ms
            logger.error(
                f"[{self.name}] 검색 실패: search_id={req.search_id}, error={e}",
                exc_info=True
            )
            req.mark_failed(error_message=str(e))
            db.commit()

    # ========== 파일 열기 ==========

    def _open_file(self, file_path: str, line_number: Optional[int] = None):
        """VSCode로 파일 열기 (유저 세션이므로 subprocess 가능).

        Args:
            file_path: 열 파일 경로
            line_number: 이동할 줄 번호 (선택)
        """
        try:
            if line_number:
                target = f"{file_path}:{line_number}"
            else:
                target = file_path

            subprocess.Popen(
                ["code", "--goto", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(f"[{self.name}] 파일 열기: {target}")
        except Exception as e:
            logger.error(f"[{self.name}] 파일 열기 실패: {file_path}, error={e}")

    # ========== 도구 상태 체크 ==========

    async def _check_tool_status(self):
        """Everything/ripgrep 상태 체크 → file_search_status 테이블 UPSERT.

        30초 간격으로 호출. API의 GET /status는 이 캐시를 조회.
        """
        from app.modules.file_search.services.everything import EverythingService
        from app.modules.file_search.services.ripgrep import RipgrepService

        everything_ok = False
        ripgrep_ok = False
        ripgrep_path = None

        # Everything 연결 테스트
        try:
            svc = EverythingService()
            ok, _msg = await svc.is_available()
            everything_ok = bool(ok)
        except Exception as e:
            logger.debug(f"[{self.name}] Everything 상태 체크 실패: {e}")

        # ripgrep 경로/버전 확인
        try:
            svc = RipgrepService()
            rg_ok, rg_path = svc.is_available()
            if rg_ok and rg_path and os.path.exists(rg_path):
                ripgrep_ok = True
                ripgrep_path = rg_path
        except Exception as e:
            logger.debug(f"[{self.name}] ripgrep 상태 체크 실패: {e}")

        # DB UPSERT (id=1 단일 행)
        db = SessionLocal()
        try:
            status = db.query(FileSearchStatus).filter_by(id=1).first()
            if status:
                status.everything_ok = everything_ok
                status.ripgrep_ok = ripgrep_ok
                status.ripgrep_path = ripgrep_path
                status.checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            else:
                status = FileSearchStatus(
                    id=1,
                    everything_ok=everything_ok,
                    ripgrep_ok=ripgrep_ok,
                    ripgrep_path=ripgrep_path,
                )
                db.add(status)
            db.commit()

            logger.debug(
                f"[{self.name}] 도구 상태 업데이트: "
                f"everything={everything_ok}, ripgrep={ripgrep_ok}"
            )
        except Exception as e:
            logger.error(f"[{self.name}] 도구 상태 DB 업데이트 실패: {e}")
        finally:
            db.close()

    # ========== stale 요청 정리 ==========

    async def _cleanup_stale_requests(self):
        """시작 시 stale 요청(10분 이상 pending/processing) → failed 처리.

        CrawlWorkerBase._cleanup_stale_requests 패턴 참조.
        """
        db = SessionLocal()
        try:
            threshold = datetime.now() - timedelta(minutes=STALE_THRESHOLD_MINUTES)
            threshold_str = threshold.strftime("%Y-%m-%d %H:%M:%S")

            stale = (
                db.query(FileSearchRequest)
                .filter(
                    FileSearchRequest.status.in_([
                        FileSearchRequest.STATUS_PENDING,
                        FileSearchRequest.STATUS_PROCESSING,
                    ]),
                    FileSearchRequest.created_at < threshold_str,
                )
                .all()
            )

            if stale:
                logger.info(f"[{self.name}] Stale 요청 {len(stale)}건 failed 처리")
                for req in stale:
                    req.mark_failed(
                        error_message=f"워커 재시작으로 인한 stale 처리 (임계값: {STALE_THRESHOLD_MINUTES}분)"
                    )
                db.commit()

        except Exception as e:
            logger.error(f"[{self.name}] Stale 요청 정리 실패: {e}")
        finally:
            db.close()

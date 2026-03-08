"""
PlanArchiveListener — Redis plan:archived 채널 구독 워커.

plan_service가 /done 처리 후 `plan:archived` 채널에 파일 경로를 publish하면,
이 워커가 수신하여 PlanRecord get_or_create → LLMRequest INSERT (중복 체크 포함).

실행:
    app/worker/main.py 에서 orchestrator에 등록하여 실행.

주요 기능:
    - Redis plan:archived pub/sub 실시간 수신
    - get_or_create로 PlanRecord 보장
    - LLMRequest 중복 체크 (같은 filename_hash + 미처리 요청 없으면 새로 생성)
    - max_retries=3 재시도 로직
"""

import asyncio
import logging
from typing import Optional

from app.shared.worker.base_worker import BaseWorker
from app.database import SessionLocal
from app.modules.dev_runner.services.plan_record_service import (
    PlanRecordService,
    _compute_filename_hash,
)
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.dev_runner.services.log_service import REDIS_HOST, REDIS_PORT

logger = logging.getLogger(__name__)

# Redis pub/sub 채널명
PLAN_ARCHIVED_CHANNEL = "plan:archived"


class PlanArchiveListener(BaseWorker):
    """Redis plan:archived 채널 구독 → LLM 분석 큐 등록 워커.

    plan:archived 채널 메시지 = archive 경로(str) 수신 시:
    1. PlanRecord get_or_create
    2. 중복 LLMRequest 체크 (pending/processing 상태)
    3. 없으면 LLMRequest INSERT (caller_type="plan_archive_analyze")

    BaseWorker 특이사항:
        - _get_loop_interval()은 pub/sub 대기 때문에 사실상 사용되지 않음
        - _main_loop_iteration()에서 subscribe 후 블로킹 대기
    """

    LOOP_INTERVAL = 1.0  # 루프 재시작 간격 (초) — 연결 끊김 시 재연결 대기

    def __init__(self):
        super().__init__("plan_archive_listener", browser_manager=None)
        self._pubsub = None
        self._redis_client = None

    def _get_loop_interval(self) -> float:
        return self.LOOP_INTERVAL

    async def _initialize(self):
        """Redis 연결 및 채널 subscribe."""
        await self._connect_redis()

    async def _connect_redis(self):
        """Redis async 클라이언트 연결 및 subscribe."""
        try:
            import redis.asyncio as aioredis

            self._redis_client = aioredis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            self._pubsub = self._redis_client.pubsub()
            await self._pubsub.subscribe(PLAN_ARCHIVED_CHANNEL)
            logger.info(
                f"[{self.name}] Redis 연결 완료 — {PLAN_ARCHIVED_CHANNEL} 구독 시작"
            )
        except Exception as e:
            logger.error(f"[{self.name}] Redis 연결 실패: {e}")
            self._pubsub = None
            self._redis_client = None

    async def _main_loop_iteration(self):
        """Redis plan:archived 채널 메시지 수신 (비동기 폴링).

        subscribe 연결이 없으면 재연결 시도.
        메시지 수신 시 _handle_archived() 호출.
        메시지 없으면 짧게 sleep 후 재시도.
        """
        # 연결이 없으면 재연결 시도
        if self._pubsub is None:
            await self._connect_redis()
            if self._pubsub is None:
                await asyncio.sleep(5)
                return

        try:
            # get_message는 non-blocking (timeout=0.5s)
            message = await self._pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=0.5,
            )
            if message and message.get("type") == "message":
                filename = message.get("data", "")
                if filename:
                    logger.info(f"[{self.name}] plan:archived 수신: {filename}")
                    await self._safe_execute(
                        "handle_archived",
                        lambda: self._handle_archived(filename),
                    )
        except Exception as e:
            logger.error(f"[{self.name}] pub/sub 수신 오류: {e}", exc_info=True)
            # 연결 오류 시 재연결을 위해 초기화
            await self._disconnect_redis()

    async def _handle_archived(self, filename: str):
        """plan:archived 메시지 처리 — LLMRequest 큐 등록.

        Args:
            filename: archive 파일 경로 (plan_service.py가 publish한 값)

        처리 흐름:
            1. PlanRecord get_or_create
            2. 중복 LLMRequest 체크 (pending/processing 상태 존재 시 skip)
            3. LLMRequest INSERT (caller_type="plan_archive_analyze")
            4. 실패 시 max_retries=3 재시도
        """
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._handle_archived_sync,
                    filename,
                )
                return  # 성공
            except Exception as e:
                logger.warning(
                    f"[{self.name}] _handle_archived 실패 "
                    f"(시도 {attempt}/{max_retries}): {e}",
                    exc_info=True,
                )
                if attempt < max_retries:
                    await asyncio.sleep(attempt)  # 지수 백오프 (1s, 2s)

        logger.error(
            f"[{self.name}] _handle_archived 최대 재시도 초과: {filename}"
        )

    def _handle_archived_sync(self, filename: str):
        """동기 버전 — DB 작업 (run_in_executor에서 실행).

        Args:
            filename: archive 파일 경로
        """
        with SessionLocal() as db:
            # 1. PlanRecord get_or_create
            svc = PlanRecordService(db)
            record = svc.get_or_create(file_path=filename)

            # filename_hash로 중복 LLMRequest 체크
            filename_hash = _compute_filename_hash(filename)
            existing = (
                db.query(LLMRequest)
                .filter(
                    LLMRequest.caller_type == "plan_archive_analyze",
                    LLMRequest.caller_id == filename_hash,
                    LLMRequest.status.in_(["pending", "processing"]),
                )
                .first()
            )

            if existing:
                logger.info(
                    f"[{self.name}] 중복 LLMRequest 스킵 "
                    f"(id={existing.id}, filename_hash={filename_hash[:8]})"
                )
                db.commit()
                return

            # 3. LLMRequest INSERT
            prompt = self._build_prompt(filename)
            req = LLMRequest(
                caller_type="plan_archive_analyze",
                caller_id=filename_hash,
                prompt=prompt,
                requested_by="plan_archive_listener",
                request_source="plan:archived",
                queue_name="utility",
                status="pending",
            )
            db.add(req)
            db.commit()
            logger.info(
                f"[{self.name}] LLMRequest 등록 완료 "
                f"(id={req.id}, file={filename})"
            )

    def _build_prompt(self, filename: str) -> str:
        """LLM 분석 프롬프트 생성.

        Args:
            filename: archive 파일 경로

        Returns:
            str: LLM 프롬프트
        """
        from pathlib import Path
        try:
            path = Path(filename)
            content = path.read_text(encoding="utf-8", errors="replace")
            filename_only = path.name
        except Exception as e:
            content = ""
            filename_only = filename
            logger.warning(f"[{self.name}] plan 파일 읽기 실패: {filename} ({e})")

        from app.modules.claude_worker.services.plan_analyze_handler import (
            build_plan_analyze_prompt,
        )
        return build_plan_analyze_prompt(file_content=content, filename=filename_only)

    async def _cleanup(self):
        """종료 시 Redis 연결 해제."""
        await self._disconnect_redis()
        await super()._cleanup()

    async def _disconnect_redis(self):
        """Redis 연결 해제."""
        try:
            if self._pubsub:
                await self._pubsub.unsubscribe(PLAN_ARCHIVED_CHANNEL)
                await self._pubsub.close()
                self._pubsub = None
            if self._redis_client:
                await self._redis_client.close()
                self._redis_client = None
        except Exception as e:
            logger.warning(f"[{self.name}] Redis 연결 해제 오류 (무시): {e}")

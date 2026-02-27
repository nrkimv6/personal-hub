"""
PlanArchiveListener — plan:archived Redis 채널 구독 워커

/done 실행 시 plan_service에서 plan:archived 채널에 archive 경로를 publish하면
이 리스너가 수신하여 LLM 분석 큐에 등록합니다.

주요 기능:
    - Redis plan:archived 채널 subscribe
    - 메시지 수신 시 plan_records DB 레코드 확인/생성
    - LLMRequest(caller_type="plan_archive_analyze") INSERT
    - 중복 pending 체크로 중복 큐 등록 방지
    - Redis 미연결 시 자동 스킵 (02:10 안전망에서 재처리)
"""
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.shared.worker.base_worker import BaseWorker
from app.database import SessionLocal
from app.shared.redis import RedisClient

logger = logging.getLogger(__name__)

# 재시도 설정
MAX_RETRIES = 3
# Redis subscribe 대기 타임아웃 (초)
SUBSCRIBE_TIMEOUT = 1.0


class PlanArchiveListener(BaseWorker):
    """plan:archived 채널 구독 → LLM 분석 큐 등록 워커"""

    def __init__(self):
        super().__init__(name="PlanArchiveListener")
        self._pubsub = None
        self._fail_counts: dict = {}  # filename_hash → 실패 횟수

    def _get_loop_interval(self) -> float:
        return 0.5  # 0.5초마다 메시지 체크

    async def _initialize(self):
        """Redis pubsub 초기화"""
        await super()._initialize()
        try:
            redis_client = await RedisClient.get_client()
            if redis_client:
                self._pubsub = redis_client.pubsub()
                await self._pubsub.subscribe("plan:archived")
                logger.info(f"[{self.name}] plan:archived 채널 subscribe 완료")
            else:
                logger.info(f"[{self.name}] Redis 미연결 — listener 비활성 (02:10 안전망 대기)")
        except Exception as e:
            logger.warning(f"[{self.name}] Redis subscribe 실패 (무시): {e}")
            self._pubsub = None

    async def _cleanup(self):
        """Redis pubsub 정리"""
        try:
            if self._pubsub:
                await self._pubsub.unsubscribe("plan:archived")
                await self._pubsub.close()
        except Exception:
            pass
        await super()._cleanup()

    async def _main_loop_iteration(self):
        """메시지 수신 및 처리"""
        if not self._pubsub:
            # Redis 미연결 — 주기적으로 재연결 시도 (60초마다)
            if not hasattr(self, "_last_reconnect_attempt"):
                self._last_reconnect_attempt = datetime.now()
            elapsed = (datetime.now() - self._last_reconnect_attempt).total_seconds()
            if elapsed >= 60:
                self._last_reconnect_attempt = datetime.now()
                await self._initialize()
            await asyncio.sleep(self._get_loop_interval())
            return

        try:
            # non-blocking으로 메시지 확인
            message = await self._pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=SUBSCRIBE_TIMEOUT
            )
            if message and message.get("type") == "message":
                archive_path = message.get("data", "")
                if isinstance(archive_path, bytes):
                    archive_path = archive_path.decode("utf-8")
                if archive_path:
                    await asyncio.get_event_loop().run_in_executor(
                        None, self._handle_archived, archive_path
                    )
        except Exception as e:
            logger.warning(f"[{self.name}] pubsub 메시지 처리 오류: {e}")
            self._pubsub = None  # 재연결 트리거

    def _handle_archived(self, archive_path: str) -> None:
        """archive 이벤트 처리 — LLM 큐 등록

        Args:
            archive_path: 아카이브된 plan 파일 경로
        """
        from app.models.plan_record import PlanRecord
        from app.modules.claude_worker.models.llm_request import LLMRequest
        from app.modules.claude_worker.services.plan_analyze_handler import (
            build_plan_analyze_prompt
        )
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService
        from sqlalchemy import and_

        db = SessionLocal()
        try:
            # 1. plan_record 확인/생성
            svc = PlanRecordService(db)
            record = svc.get_or_create(archive_path)
            db.commit()
            db.refresh(record)

            filename_hash = record.filename_hash

            # 2. 실패 카운트 초과 체크
            fail_count = self._fail_counts.get(filename_hash, 0)
            if fail_count >= MAX_RETRIES:
                logger.error(
                    f"[{self.name}] 최대 재시도 초과, skip: {archive_path} (fail={fail_count})"
                )
                return

            # 3. 중복 pending 체크
            existing = db.query(LLMRequest).filter(
                and_(
                    LLMRequest.caller_type == "plan_archive_analyze",
                    LLMRequest.caller_id == filename_hash,
                    LLMRequest.status == "pending",
                )
            ).first()
            if existing:
                logger.debug(f"[{self.name}] 중복 pending skip: {archive_path}")
                return

            # 4. 파일 내용 읽기
            file_content = ""
            try:
                fp = Path(archive_path)
                if fp.exists():
                    file_content = fp.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.warning(f"[{self.name}] 파일 읽기 실패 ({archive_path}): {e}")

            # 5. LLMRequest INSERT
            prompt = build_plan_analyze_prompt(
                file_content=file_content,
                filename=Path(archive_path).name,
            )
            llm_req = LLMRequest(
                caller_type="plan_archive_analyze",
                caller_id=filename_hash,
                prompt=prompt,
                queue_name="utility",
                requested_by="scheduler",
            )
            db.add(llm_req)
            db.commit()
            logger.info(f"[{self.name}] LLMRequest 등록: {Path(archive_path).name}")

        except Exception as e:
            logger.error(f"[{self.name}] _handle_archived 오류 ({archive_path}): {e}", exc_info=True)
            self._fail_counts[filename_hash if 'filename_hash' in dir() else archive_path] = (
                self._fail_counts.get(archive_path, 0) + 1
            )
            db.rollback()
        finally:
            db.close()

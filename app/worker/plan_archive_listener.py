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
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from app.shared.worker.base_worker import BaseWorker
from app.database import SessionLocal
from app.modules.dev_runner.services.plan_record_service import (
    PlanRecordService,
    _compute_filename_hash,
)
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.services.plan_archive_prompt_policy import (
    DEFAULT_CATEGORIES,
    PromptPolicyContext,
    build_plan_archive_prompt,
)
from app.modules.dev_runner.services.log_service import REDIS_HOST, REDIS_PORT
from app.modules.dev_runner.services.sse_helpers import safe_close_pubsub

logger = logging.getLogger(__name__)

# Redis pub/sub 채널명
PLAN_ARCHIVED_CHANNEL = "plan:archived"

# monitor-page 레포 루트 (plan_archive_listener.py → worker → app → monitor-page)
_REPO_ROOT = Path(__file__).resolve().parents[2]


def get_git_first_commit_date(file_path: str) -> "date | None":
    """git 히스토리에서 파일의 최초 커밋 날짜를 반환.

    Args:
        file_path: 파일 경로 (절대 또는 상대)

    Returns:
        date 객체 또는 None (미추적/오류 시)
    """
    try:
        result = subprocess.run(
            ["git", "log", "--follow", "--diff-filter=A", "--format=%ai", "--", file_path],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        stdout = result.stdout.strip()
        if not stdout:
            return None
        first_line = stdout.splitlines()[0].strip()
        # "2026-01-15 13:52:00 +0900" 형식에서 날짜 파싱
        date_part = first_line.split(" ")[0]
        parts = date_part.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return None


def parse_applied_at(content: str) -> "datetime | None":
    """plan 파일 내용에서 > 반영일: 헤더를 파싱.

    Args:
        content: plan 파일 전체 내용

    Returns:
        datetime 객체 또는 None (헤더 없으면)
    """
    match = re.search(
        r'>\s*반영일:\s*(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)',
        content,
    )
    if not match:
        return None
    value = match.group(1).strip()
    if len(value) == 10:  # "YYYY-MM-DD"
        parts = value.split("-")
        return datetime(int(parts[0]), int(parts[1]), int(parts[2]), 0, 0)
    else:  # "YYYY-MM-DD HH:MM"
        date_part, time_part = value.split(" ", 1)
        d = date_part.split("-")
        t = time_part.split(":")
        return datetime(int(d[0]), int(d[1]), int(d[2]), int(t[0]), int(t[1]))


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
            self._log_worker_error("pub/sub 수신", e)
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

            # plan_date: git 첫 커밋 날짜
            if record.plan_date is None:
                record.plan_date = get_git_first_commit_date(filename)

            # DB-first: raw_content 우선, 없으면 파일 읽기 fallback
            file_content = record.raw_content or ""
            if not file_content:
                try:
                    file_content = Path(filename).read_text(encoding="utf-8", errors="replace")
                    if file_content:
                        record.raw_content = file_content
                except Exception as e:
                    logger.error(
                        f"[{self.name}] plan 파일 읽기 실패: {filename} ({e})"
                    )

            # applied_at: 이미 로드된 file_content로 파싱
            if record.applied_at is None and file_content:
                record.applied_at = parse_applied_at(file_content)

            if file_content:
                try:
                    from app.modules.dev_runner.services.plan_archive_relation_service import (
                        PlanArchiveRelationService,
                    )

                    PlanArchiveRelationService(db).refresh_relations_for_record(record.id)
                except Exception as relation_error:
                    logger.warning(
                        f"[{self.name}] relation refresh skipped: {filename} ({relation_error})"
                    )

            # 빈 내용 skip 가드: LLMRequest 생성 억제
            if not file_content:
                logger.error(
                    f"[{self.name}] 빈 내용 — LLMRequest 생성 스킵: {filename}"
                )
                db.commit()
                return

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

            # LLMRequest INSERT
            llm_service = LLMService(db)
            provider, model = llm_service.resolve_provider_model(
                caller_type="plan_archive_analyze",
                provider=None,
                model=None,
            )
            prompt, policy_id, policy_version = self._build_prompt_with_policy(
                filename,
                file_content=file_content,
                provider=provider,
                model=model,
            )
            req = LLMRequest(
                caller_type="plan_archive_analyze",
                caller_id=filename_hash,
                prompt=prompt,
                requested_by="plan_archive_listener",
                request_source="plan:archived",
                queue_name="utility",
                status="pending",
                provider=provider,
                model=model,
            )
            db.add(req)
            db.commit()
            logger.info(
                f"[{self.name}] LLMRequest 등록 완료 "
                f"(id={req.id}, file={filename}, policy_id={policy_id}, "
                f"policy_version={policy_version})"
            )

    def _build_prompt(
        self,
        filename: str,
        file_content: str = "",
        provider: str | None = None,
        model: str | None = None,
    ) -> str:
        """LLM 분석 프롬프트 생성.

        Args:
            filename: archive 파일 경로
            file_content: 이미 로드된 파일 내용 (없으면 파일에서 읽기)
            provider: provider-aware policy를 적용할 때 전달
            model: model-aware policy를 적용할 때 전달

        Returns:
            str: LLM 프롬프트
        """
        if provider is not None or model is not None:
            prompt, _policy_id, _policy_version = self._build_prompt_with_policy(
                filename,
                file_content=file_content,
                provider=provider or "claude",
                model=model or "",
            )
            return prompt

        from pathlib import Path
        if file_content:
            filename_only = Path(filename).name
        else:
            try:
                path = Path(filename)
                file_content = path.read_text(encoding="utf-8", errors="replace")
                filename_only = path.name
            except Exception as e:
                file_content = ""
                filename_only = Path(filename).name
                logger.error(f"[{self.name}] plan 파일 읽기 실패: {filename} ({e})")

        from app.modules.claude_worker.services.plan_analyze_handler import (
            build_plan_analyze_prompt,
        )
        return build_plan_analyze_prompt(file_content=file_content, filename=filename_only)

    def _build_prompt_with_policy(
        self,
        filename: str,
        file_content: str = "",
        provider: str = "claude",
        model: str = "",
    ) -> tuple[str, str, str]:
        """LLM 분석 프롬프트와 policy metadata를 생성."""
        if file_content:
            filename_only = Path(filename).name
        else:
            try:
                path = Path(filename)
                file_content = path.read_text(encoding="utf-8", errors="replace")
                filename_only = path.name
            except Exception as e:
                file_content = ""
                filename_only = Path(filename).name
                logger.error(f"[{self.name}] plan 파일 읽기 실패: {filename} ({e})")

        return build_plan_archive_prompt(
            PromptPolicyContext(
                caller_type="plan_archive_analyze",
                provider=provider,
                model=model,
                filename=filename_only,
                existing_categories=DEFAULT_CATEGORIES,
            ),
            file_content,
        )

    async def _cleanup(self):
        """종료 시 Redis 연결 해제."""
        await self._disconnect_redis()
        await super()._cleanup()

    async def _disconnect_redis(self):
        """Redis 연결 해제."""
        try:
            await safe_close_pubsub(self._pubsub)
            self._pubsub = None
            if self._redis_client:
                await self._redis_client.close()
                self._redis_client = None
        except Exception as e:
            logger.warning(f"[{self.name}] Redis 연결 해제 오류 (무시): {e}")

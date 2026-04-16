"""LLMQueueService — 큐 enqueue/dequeue, 상태 변경.

DB 접근: LLMRequestRepository 경유.
의존: LLMConfigService (enqueue 시 resolve_provider_model)
"""

import json
import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.modules.claude_worker.models.llm_request import LLMRequest

logger = logging.getLogger("claude_worker.llm_queue_service")

# 큐 우선순위 — 앞에 있을수록 먼저 처리
QUEUE_PRIORITY = ["system", "utility"]


class LLMQueueService:
    """큐 enqueue/dequeue + 상태 변경."""

    def __init__(self, repo, config_svc, db: Session):
        self._repo = repo
        self._config_svc = config_svc
        self.db = db

    # ── enqueue / dequeue ─────────────────────────────────────────────────────

    def enqueue(
        self,
        caller_type: str,
        caller_id: str,
        prompt: str,
        requested_by: str = "unknown",
        request_source: str = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        cli_options: dict = None,
        queue_name: str = "utility",
        mode: str = "single",
    ) -> LLMRequest:
        """요청을 큐에 추가 (non-blocking).

        Args:
            caller_type: 호출자 타입 (예: 'instagram')
            caller_id: 호출자 측 ID (예: post_id)
            prompt: LLM에 전달할 프롬프트
            requested_by: 요청자 (예: 'api', 'scheduler', 'manual')
            request_source: 요청 출처 (예: 'instagram_crawl', 'manual_test')
            provider: LLM Provider (미지정 시 caller/global 설정 fallback)
            model: 모델명 (미지정 시 caller/global 설정 fallback)
            cli_options: CLI 옵션 dict (output_format, json_schema, allowed_tools 등)
            queue_name: 큐 이름 ('utility' 또는 'system', 기본값: 'utility')
            mode: 모드 (기본값: 'single')

        Returns:
            생성된 LLMRequest
        """
        # 중복 pending 요청 확인 (같은 queue_name 내에서만)
        existing = self._repo.find_existing_pending(caller_type, caller_id, queue_name)
        if existing:
            logger.debug(f"이미 pending 요청 존재: {caller_type}:{caller_id} (queue={queue_name})")
            return existing

        resolved_provider, resolved_model = self._config_svc.resolve_provider_model(
            caller_type=caller_type,
            provider=provider,
            model=model,
        )

        request = LLMRequest(
            caller_type=caller_type,
            caller_id=caller_id,
            prompt=prompt,
            status="pending",
            requested_by=requested_by,
            request_source=request_source,
            provider=resolved_provider,
            model=resolved_model,
            cli_options=json.dumps(cli_options, ensure_ascii=False) if cli_options else None,
            queue_name=queue_name,
            mode=mode,
        )
        self._repo.add(request)
        self.db.commit()
        self.db.refresh(request)

        logger.info(
            f"LLM 요청 생성: id={request.id}, caller={caller_type}:{caller_id}, "
            f"queue={queue_name}, mode={mode}, by={requested_by}"
        )
        return request

    def update_chat_session(self, request_id: int, chat_session_id: str) -> None:
        """chat_session_id DB 업데이트."""
        request = self._repo.get_by_id(request_id)
        if request:
            request.chat_session_id = chat_session_id
            self.db.commit()

    def get_result(
        self,
        caller_type: str,
        caller_id: str,
    ) -> Optional[LLMRequest]:
        """결과 조회 (가장 최근 요청 반환)."""
        return self._repo.find_latest_by_caller(caller_type, caller_id)

    def get_pending_request(self) -> Optional[LLMRequest]:
        """가장 오래된 pending 요청 조회 (레거시 — get_next_request 사용 권장)."""
        return self._repo.find_oldest_pending()

    def get_next_request(self, exclude_providers: list = None) -> Optional[LLMRequest]:
        """우선순위 기반으로 다음 처리할 요청 조회 (워커용).

        QUEUE_PRIORITY 순서로 각 큐를 확인하여 가장 오래된 pending 요청 반환.
        현재 우선순위: system → utility

        Args:
            exclude_providers: 제외할 provider 목록 (예: ["gemini"])

        Returns:
            pending 요청 또는 None
        """
        if exclude_providers is None:
            exclude_providers = []

        for queue in QUEUE_PRIORITY:
            request = self._repo.find_next_pending_in_queue(queue, exclude_providers)
            if request:
                return request
        return None

    # ── 통계 ──────────────────────────────────────────────────────────────────

    def get_queue_stats(self) -> dict:
        """큐별 상태 카운트 통계.

        Returns:
            {"system": {"pending": N, "processing": N, ...}, "utility": {...}}
        """
        rows = self._repo.get_queue_stats_rows()

        result: dict = {}
        for queue in QUEUE_PRIORITY:
            result[queue] = {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "cancelled": 0}

        for row in rows:
            queue = row.queue_name or "utility"
            if queue not in result:
                result[queue] = {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "cancelled": 0}
            status = row.status
            if status in result[queue]:
                result[queue][status] = row.cnt

        return result

    def get_pending_count(self) -> int:
        """Pending 요청 수 조회."""
        return self._repo.count_pending()

    # ── 상태 변경 ──────────────────────────────────────────────────────────────

    def mark_processing(self, request_id: int) -> None:
        """요청을 processing 상태로 변경."""
        request = self._repo.get_by_id(request_id)
        if request:
            request.status = "processing"
            self.db.commit()

    def mark_completed(
        self,
        request_id: int,
        result: dict,
        raw_response: str = "",
        claude_session_id: Optional[str] = None,
    ) -> None:
        """요청을 completed 상태로 변경."""
        request = self.prepare_completed(
            request_id,
            result,
            raw_response,
            claude_session_id,
        )
        if request:
            self.db.commit()

    def prepare_completed(
        self,
        request_id: int,
        result: dict,
        raw_response: str = "",
        claude_session_id: Optional[str] = None,
    ) -> Optional[LLMRequest]:
        """요청의 completed 필드를 채우되 commit은 호출자가 결정한다."""
        request = self._repo.get_by_id(request_id)
        if request:
            request.status = "completed"
            request.processed_at = datetime.now()
            request.result = json.dumps(result, ensure_ascii=False)
            request.raw_response = raw_response
            request.error_message = None
            if claude_session_id:
                request.claude_session_id = claude_session_id
            return request
        return None

    def mark_failed(self, request_id: int, error_message: str, raw_response: str = "") -> None:
        """요청을 failed 상태로 변경."""
        request = self._repo.get_by_id(request_id)
        if request:
            request.status = "failed"
            request.processed_at = datetime.now()
            request.error_message = error_message
            if raw_response:
                request.raw_response = raw_response
            request.retry_count += 1
            self.db.commit()

    def reset_to_pending(self, request_id: int) -> bool:
        """요청을 pending으로 리셋 (재시도용).

        failed 상태인 요청만 pending으로 변경할 수 있습니다.
        completed 상태는 이미 처리 완료되었으므로 리셋 불가.
        """
        request = self._repo.get_by_id(request_id)
        if request and request.status == "failed":
            request.status = "pending"
            request.error_message = None
            request.result = None
            request.raw_response = None
            request.processed_at = None
            self.db.commit()
            return True
        return False

"""Plan Archive Execution Service — archive 분석 요청 큐 등록.

archive record에 대해 특정 provider/model로 LLM 분석을 요청한다.
profile-less provider(codex 등)도 지원한다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.modules.claude_worker.models.llm_request import LLMRequest
from app.models.plan_record import PlanRecord

logger = logging.getLogger(__name__)


class PlanArchiveExecutionService:
    """Archive 분석 LLM 요청 큐잉 서비스.

    profile-backed provider(claude/gemini)와 profile-less provider(codex/cc-codex) 모두
    동일한 인터페이스로 큐잉한다. profile_key가 None이면 profile 선택을 생략한다.
    """

    CALLER_TYPE = "plan_archive_analyze"

    def __init__(self, db: Session) -> None:
        self._db = db

    def queue_analysis(
        self,
        record: PlanRecord,
        provider: str,
        model: str = "",
        profile_key: Optional[str] = None,
    ) -> Tuple[LLMRequest, bool]:
        """archive record에 대해 LLM 분석 요청을 큐에 등록한다.

        Args:
            record: PlanRecord 인스턴스
            provider: 실행 provider ('claude', 'gemini', 'codex', 'cc-codex')
            model: 모델명. 빈 문자열이면 provider 기본 모델 사용
            profile_key: profile 이름 (claude/gemini용 optional). codex는 무시됨.

        Returns:
            (LLMRequest, created): created=False이면 기존 pending 요청 재사용

        Raises:
            ValueError: 지원하지 않는 provider이거나 record.filename_hash 없을 때
        """
        from app.modules.claude_worker.services.provider_registry import is_supported
        if not is_supported(provider):
            raise ValueError(f"unsupported provider: {provider!r}")

        filename_hash = record.filename_hash
        if not filename_hash:
            raise ValueError(f"record id={record.id} has no filename_hash")

        # pending/processing 중복 요청 체크
        existing = (
            self._db.query(LLMRequest)
            .filter(
                LLMRequest.caller_type == self.CALLER_TYPE,
                LLMRequest.caller_id == filename_hash,
                LLMRequest.provider == provider,
                LLMRequest.status.in_(["pending", "processing"]),
            )
            .first()
        )
        if existing:
            logger.info(
                "[exec-svc] 중복 요청 스킵: record_id=%s filename_hash=%s provider=%s request_id=%s",
                record.id, filename_hash[:8], provider, existing.id,
            )
            return existing, False

        prompt = self._build_prompt(record)
        req = LLMRequest(
            caller_type=self.CALLER_TYPE,
            caller_id=filename_hash,
            prompt=prompt,
            requested_by="api",
            request_source="manual_reanalyze",
            queue_name="utility",
            status="pending",
            provider=provider,
            model=model,
        )
        self._db.add(req)
        logger.info(
            "[exec-svc] 분석 요청 큐 등록: record_id=%s provider=%s model=%s profile_key=%s",
            record.id, provider, model or "(default)", profile_key,
        )
        return req, True

    def _build_prompt(self, record: PlanRecord) -> str:
        """plan 파일 내용을 읽어 분석 프롬프트를 생성한다.

        파일이 없으면 raw_content fallback을 사용한다.
        """
        from app.modules.claude_worker.services.plan_analyze_handler import build_plan_analyze_prompt

        try:
            path = Path(record.file_path)
            content = path.read_text(encoding="utf-8", errors="replace")
            filename_only = path.name
        except Exception:
            content = record.raw_content or ""
            filename_only = Path(record.file_path).name if record.file_path else "unknown.md"

        return build_plan_analyze_prompt(file_content=content, filename=filename_only)

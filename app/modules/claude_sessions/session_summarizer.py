"""SessionSummarizer — Claude 세션 요약을 LLM Worker 큐에 enqueue."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.claude_sessions.session_parser import SessionParser
from app.modules.claude_worker.models.llm_request import LLMRequest

logger = logging.getLogger("claude_sessions.session_summarizer")

_parser = SessionParser()

CALLER_TYPE = "claude_session_summary"
MODEL = "claude-haiku-4-5-20251001"
QUEUE_NAME = "utility"


class SessionSummarizer:
    """세션 요약 enqueue 및 결과 조회."""

    def __init__(self, db: Session):
        self.db = db
        from app.modules.claude_worker.services.llm_service import LLMService
        self._llm = LLMService(db)

    def enqueue_summary(
        self, session_id: str, project_path: str
    ) -> LLMRequest:
        """단일 세션 요약 enqueue."""
        sessions_dir = _parser.get_sessions_dir(project_path)
        jsonl_path = sessions_dir / f"{session_id}.jsonl"

        meta_list = _parser.list_sessions(project_path, limit=200)
        meta = next((m for m in meta_list if m.id == session_id), None)

        if meta is None:
            # 파일이 있더라도 meta 없으면 최소 생성
            from pathlib import Path
            from datetime import datetime
            from app.modules.claude_sessions.session_parser import SessionMeta
            stat = jsonl_path.stat()
            meta = SessionMeta(
                id=session_id,
                path=jsonl_path,
                mtime=datetime.fromtimestamp(stat.st_mtime),
                line_count=0,
                source_type="unknown",
            )

        messages = _parser.extract_messages(jsonl_path)
        prompt = _parser.build_summary_prompt(messages, meta)

        return self._llm.enqueue(
            caller_type=CALLER_TYPE,
            caller_id=session_id,
            prompt=prompt,
            requested_by="api",
            model=MODEL,
            queue_name=QUEUE_NAME,
        )

    def get_summary_result(self, session_id: str) -> Optional[LLMRequest]:
        """요약 결과 조회."""
        return self._llm.get_result(CALLER_TYPE, session_id)

    def enqueue_batch(
        self, session_ids: list[str], project_path: str
    ) -> list[LLMRequest]:
        """여러 세션 일괄 enqueue."""
        results: list[LLMRequest] = []
        for sid in session_ids:
            try:
                req = self.enqueue_summary(sid, project_path)
                results.append(req)
            except Exception as e:
                logger.warning(f"세션 요약 enqueue 실패: {sid} — {e}")
        return results

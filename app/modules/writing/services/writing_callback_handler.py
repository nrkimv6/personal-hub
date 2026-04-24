"""WritingCallbackHandler - 글쓰기 LLM 콜백 처리.

Claude Worker에서 호출되어 LLM 결과를 저장하고 배치 상태를 업데이트합니다.
"""

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.writing import GeneratedWriting
from app.models.writing_element import WritingElement, WritingElementUsage
from app.modules.writing.models.writing_batch import WritingBatch
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.core.database import is_connection_error


logger = logging.getLogger(__name__)


class WritingCallbackHandler:
    """글쓰기 LLM 콜백 처리기.

    LLM 결과를 받아서:
    1. GeneratedWriting 저장
    2. WritingElementUsage 기록
    3. WritingBatch 카운트 업데이트
    """

    def __init__(self, db: Session):
        self.db = db

    def handle_success(
        self,
        request: LLMRequest,
        llm_result: dict,
        raw_response: str,
    ) -> Optional[GeneratedWriting]:
        """LLM 성공 결과 처리.

        Args:
            request: LLM 요청 객체
            llm_result: LLM 파싱 결과 (dict)
            raw_response: LLM 원본 응답

        Returns:
            생성된 GeneratedWriting 또는 None
        """
        try:
            # 메타데이터 파싱
            metadata = self._parse_metadata(request.writing_metadata)
            task_type = metadata.get("task_type", "unknown")

            # 콘텐츠 추출
            content = self._extract_content(llm_result, raw_response)
            if not content:
                logger.warning(f"콘텐츠 추출 실패: request_id={request.id}")
                return self._handle_failure_internal(request, "콘텐츠 추출 실패")

            # GeneratedWriting 생성
            writing = GeneratedWriting(
                task_type=task_type,
                content=content[:10000],
                raw_response=raw_response[:50000] if raw_response else None,
                llm_request_id=request.id,
            )

            # 메타데이터 기반 필드 설정
            self._set_writing_metadata(writing, metadata, task_type)

            self.db.add(writing)
            self.db.flush()  # ID 생성

            # 요소 사용 이력 기록
            self._record_element_usage(metadata, writing.id)

            # 배치 카운트 업데이트
            self._update_batch_completed(request.writing_batch_id)

            self.db.commit()
            logger.info(
                f"글쓰기 결과 저장: writing_id={writing.id}, "
                f"task_type={task_type}, batch_id={request.writing_batch_id}"
            )
            return writing

        except Exception as e:
            self.db.rollback()
            if is_connection_error(e):
                logger.warning(f"PG 연결 오류 (글쓰기 결과 처리): {e}")
            else:
                logger.error(f"글쓰기 결과 처리 실패: {e}", exc_info=True)
            return None

    def handle_failure(
        self,
        request: LLMRequest,
        error_message: str,
    ) -> bool:
        """LLM 실패 처리.

        Args:
            request: LLM 요청 객체
            error_message: 에러 메시지

        Returns:
            성공 여부
        """
        return self._handle_failure_internal(request, error_message)

    def _handle_failure_internal(
        self,
        request: LLMRequest,
        error_message: str,
    ) -> bool:
        """내부 실패 처리."""
        try:
            # 배치 카운트 업데이트
            self._update_batch_failed(request.writing_batch_id)

            self.db.commit()
            logger.warning(
                f"글쓰기 실패 처리: request_id={request.id}, "
                f"batch_id={request.writing_batch_id}, error={error_message}"
            )
            return True

        except Exception as e:
            self.db.rollback()
            if is_connection_error(e):
                logger.warning(f"PG 연결 오류 (글쓰기 실패 처리): {e}")
            else:
                logger.error(f"글쓰기 실패 처리 중 에러: {e}", exc_info=True)
            return False

    def _parse_metadata(self, metadata_json: Optional[str]) -> dict:
        """메타데이터 파싱."""
        if not metadata_json:
            return {}
        try:
            return json.loads(metadata_json)
        except json.JSONDecodeError:
            return {}

    def _extract_content(
        self,
        llm_result: Optional[dict],
        raw_response: str,
    ) -> str:
        """콘텐츠 추출.

        LLM 결과에서 글 내용을 추출합니다.
        JSON 구조에서 content 필드를 찾거나, 전체 raw_response를 사용합니다.
        """
        # 우선 raw_response 사용 (글쓰기는 전체 응답이 콘텐츠)
        if raw_response:
            return raw_response.strip()

        # JSON 결과에서 content 추출 시도
        if llm_result:
            if isinstance(llm_result, dict):
                if "content" in llm_result:
                    return str(llm_result["content"])
                # 전체 dict를 문자열로 변환
                return json.dumps(llm_result, ensure_ascii=False)
            return str(llm_result)

        return ""

    def _set_writing_metadata(
        self,
        writing: GeneratedWriting,
        metadata: dict,
        task_type: str,
    ):
        """GeneratedWriting에 메타데이터 설정."""
        if task_type == "mix":
            source_ids = metadata.get("source_ids", [])
            if source_ids:
                writing.source_ids = json.dumps(source_ids)
        elif task_type in ["random", "keyword"]:
            selected = metadata.get("selected_elements", {})
            writing.selected_elements = json.dumps(selected, ensure_ascii=False)

    def _record_element_usage(self, metadata: dict, writing_id: int):
        """요소 사용 이력 기록."""
        task_type = metadata.get("task_type", "")

        # Mix: source_ids 기록
        if task_type == "mix":
            source_ids = metadata.get("source_ids", [])
            for source_id in source_ids:
                usage = WritingElementUsage(
                    source_id=source_id,
                    generated_writing_id=writing_id,
                )
                self.db.add(usage)

        # Random/Keyword: element_ids 기록
        elif task_type in ["random", "keyword"]:
            # topic_id
            topic_id = metadata.get("topic_id")
            if topic_id:
                usage = WritingElementUsage(
                    element_id=topic_id,
                    generated_writing_id=writing_id,
                )
                self.db.add(usage)

            # keyword_ids
            keyword_ids = metadata.get("keyword_ids", [])
            for kw_id in keyword_ids:
                usage = WritingElementUsage(
                    element_id=kw_id,
                    generated_writing_id=writing_id,
                )
                self.db.add(usage)

    def _update_batch_completed(self, batch_id: Optional[int]):
        """배치 완료 카운트 업데이트."""
        if not batch_id:
            return

        batch = (
            self.db.query(WritingBatch)
            .filter(WritingBatch.id == batch_id)
            .first()
        )
        if batch:
            batch.increment_completed()
            logger.debug(
                f"배치 진행: batch_id={batch_id}, "
                f"completed={batch.completed_count}/{batch.total_count}"
            )

    def _update_batch_failed(self, batch_id: Optional[int]):
        """배치 실패 카운트 업데이트."""
        if not batch_id:
            return

        batch = (
            self.db.query(WritingBatch)
            .filter(WritingBatch.id == batch_id)
            .first()
        )
        if batch:
            batch.increment_failed()
            logger.debug(
                f"배치 실패: batch_id={batch_id}, "
                f"failed={batch.failed_count}/{batch.total_count}"
            )

"""
Topic Extract Worker - 기존 소스에서 소재만 추출하는 워커.

writing_sources에서 미처리 글을 읽어 소재를 추출하고 writing_elements에 저장.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.models.writing import WritingSource
from app.models.writing_element import WritingElement
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.models.llm_request import LLMRequest

logger = logging.getLogger(__name__)


class TopicExtractWorker:
    """기존 소스에서 소재만 추출하는 워커."""

    BATCH_SIZE = 10  # 한 번에 LLM에 보낼 소스 수
    DAILY_LIMIT = 100  # 하루 처리량
    LLM_TIMEOUT = 120  # 타임아웃 (초)

    # 프롬프트 파일 경로
    PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "topic_extract_prompt.md"

    def __init__(self, db: Session):
        """TopicExtractWorker 초기화."""
        self.db = db
        self.llm_service = LLMService(db)
        self._load_prompt()

    def _load_prompt(self):
        """프롬프트 파일 로드."""
        if self.PROMPT_PATH.exists():
            self.prompt_template = self.PROMPT_PATH.read_text(encoding="utf-8")
            logger.debug(f"Topic extract prompt loaded from {self.PROMPT_PATH}")
        else:
            self.prompt_template = ""
            logger.warning(f"Topic extract prompt not found: {self.PROMPT_PATH}")

    def run(self, schedule: TaskSchedule, run: TaskScheduleRun) -> dict:
        """워커 실행 (비동기 큐 패턴).

        Args:
            schedule: 스케줄 설정
            run: 실행 기록

        Returns:
            {"total": 요청수, "extracted": 0, "failed": 0}
        """
        logger.info(f"TopicExtractWorker 시작: schedule_id={schedule.id}, run_id={run.id}")

        try:
            # target_config에서 LLM provider/model 읽기
            config = schedule.get_target_config() if schedule.target_config else {}
            llm_provider = config.get("llm_provider")
            llm_model = config.get("llm_model")

            # 비동기 요청 생성 (create_extract_requests 사용)
            request_count = self.create_extract_requests(limit=self.DAILY_LIMIT, llm_provider=llm_provider, llm_model=llm_model)

            # 완료 처리 (Worker가 실제 추출 수행)
            run.mark_completed(
                collected_count=request_count,
                saved_count=0,  # Worker가 처리하므로 0
                stop_reason="requests_created"
            )
            self.db.commit()

            logger.info(f"TopicExtractWorker 완료: {request_count}개 요청 생성")

            return {"total": request_count, "extracted": 0, "failed": 0}

        except Exception as e:
            logger.error(f"TopicExtractWorker 실행 실패: {e}", exc_info=True)
            run.mark_failed(str(e))
            self.db.commit()
            raise

    def _get_unprocessed_sources(self, limit: int) -> list[WritingSource]:
        """미처리 소스 조회."""
        return (
            self.db.query(WritingSource)
            .filter(WritingSource.topic_extracted_at.is_(None))
            .order_by(WritingSource.id)
            .limit(limit)
            .all()
        )

    def _process_batch(self, sources: list[WritingSource], run_id: int, batch_num: int) -> int:
        """배치 처리.

        Args:
            sources: 소스 리스트
            run_id: 실행 ID
            batch_num: 배치 번호

        Returns:
            추출된 소재 수
        """
        # 프롬프트 구성
        sources_text = "\n\n".join([
            f"[글 {s.id}]\n{s.content[:2000]}"  # 글 당 최대 2000자
            for s in sources
        ])
        prompt = self.prompt_template.replace("{sources}", sources_text)
        provider, model = self.llm_service.resolve_provider_model(
            caller_type="topic_extract",
            provider=None,
            model=None,
        )

        # LLM 요청 생성
        llm_request = LLMRequest(
            caller_type="topic_extract",
            caller_id=f"batch_{run_id}_{batch_num}",
            prompt=prompt[:5000] if len(prompt) > 5000 else prompt,
            status="processing",
            requested_by="scheduler",
            request_source="topic_extract_worker",
            provider=provider,
            model=model,
        )
        self.db.add(llm_request)
        self.db.commit()
        self.db.refresh(llm_request)

        try:
            # LLM 호출 (글쓰기는 도구 사용 금지)
            result = self.llm_service.execute_llm(
                prompt=prompt,
                provider=provider,
                model=model,
                timeout=self.LLM_TIMEOUT,
                parse_json=True,
                enable_tools=False,
            )

            if not result.get("success"):
                error_msg = result.get("error", "Unknown error")
                logger.error(f"LLM 호출 실패: {error_msg}")
                llm_request.status = "failed"
                llm_request.error_message = error_msg
                llm_request.processed_at = datetime.now()
                self.db.commit()
                return 0

            # 결과 처리
            raw_response = result.get("raw_response", "")
            parsed_result = result.get("result", {})
            topics = parsed_result.get("topics", [])

            llm_request.status = "completed"
            llm_request.raw_response = raw_response
            llm_request.result = json.dumps(parsed_result, ensure_ascii=False)
            llm_request.processed_at = datetime.now()
            self.db.commit()

            # 소재 저장
            extracted_count = self._save_topics(topics)

            # 소스 처리 완료 마킹
            source_ids = {s.id for s in sources}
            for topic_item in topics:
                source_id = topic_item.get("source_id")
                if source_id in source_ids:
                    source_ids.discard(source_id)

            # 모든 소스 처리 완료 마킹 (추출 실패한 것도 포함)
            for source in sources:
                source.topic_extracted_at = datetime.now()
            self.db.commit()

            return extracted_count

        except Exception as e:
            logger.error(f"배치 처리 중 오류: {e}", exc_info=True)
            llm_request.status = "failed"
            llm_request.error_message = str(e)
            llm_request.processed_at = datetime.now()
            self.db.commit()
            raise

    def _save_topics(self, topics: list[dict]) -> int:
        """추출된 소재 저장.

        Args:
            topics: [{"source_id": 123, "topic": "소재"}, ...]

        Returns:
            저장된 소재 수
        """
        saved_count = 0

        for item in topics:
            topic = item.get("topic", "").strip()
            if not topic or len(topic) < 2:
                continue

            # 너무 짧거나 일반적인 단어 필터링
            if len(topic) <= 3 and topic in ["사랑", "마음", "추억", "가족", "행복"]:
                continue

            try:
                # 중복 체크
                existing = (
                    self.db.query(WritingElement)
                    .filter(
                        WritingElement.category == WritingElement.CATEGORY_TOPIC,
                        WritingElement.name == topic,
                    )
                    .first()
                )

                if existing:
                    if existing.frequency:
                        existing.frequency += 1
                    else:
                        existing.frequency = 2
                else:
                    new_element = WritingElement(
                        category=WritingElement.CATEGORY_TOPIC,
                        name=topic,
                        source_type=WritingElement.SOURCE_TYPE_AUTO,
                        frequency=1,
                        is_active=True,
                    )
                    self.db.add(new_element)

                saved_count += 1

            except Exception as e:
                logger.warning(f"소재 저장 실패: {topic} - {e}")
                continue

        if saved_count:
            self.db.commit()
            logger.info(f"소재 {saved_count}개 저장 완료")

        return saved_count

    def create_extract_requests(
        self,
        limit: int = 100,
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None,
    ) -> int:
        """소재 추출 LLM 요청 생성 (시범용).

        스케줄 없이 직접 LLMRequest를 생성합니다.
        Claude Worker가 처리하면 소재가 추출됩니다.

        Args:
            limit: 처리할 소스 수

        Returns:
            생성된 요청 수
        """
        sources = self._get_unprocessed_sources(limit=limit)
        if not sources:
            logger.info("처리할 소스가 없습니다.")
            return 0

        request_count = 0

        for i in range(0, len(sources), self.BATCH_SIZE):
            batch = sources[i:i + self.BATCH_SIZE]
            batch_num = i // self.BATCH_SIZE + 1

            # 프롬프트 구성
            sources_text = "\n\n".join([
                f"[글 {s.id}]\n{s.content[:2000]}"
                for s in batch
            ])
            prompt = self.prompt_template.replace("{sources}", sources_text)

            # source_id 전체 기록 (추적 및 중복 감지용)
            source_ids = [s.id for s in batch]
            source_ids_str = ",".join(str(sid) for sid in source_ids)
            provider, model = self.llm_service.resolve_provider_model(
                caller_type="topic_extract",
                provider=llm_provider,
                model=llm_model,
            )

            # LLM 요청 생성 (pending 상태)
            llm_request = LLMRequest(
                caller_type="topic_extract",
                caller_id=f"src:{source_ids_str}",  # 예: src:101,102,103,104,105
                prompt=prompt,
                status="pending",  # Claude Worker가 처리
                requested_by="manual",
                request_source="topic_extract_worker",
                provider=provider,
                model=model,
            )
            self.db.add(llm_request)
            request_count += 1

            # 소스 처리 완료 마킹
            for source in batch:
                source.topic_extracted_at = datetime.now()

        self.db.commit()
        logger.info(f"LLM 요청 {request_count}개 생성 완료")
        return request_count


def run_topic_extract_sync(
    db: Session,
    schedule: TaskSchedule,
    run: TaskScheduleRun,
) -> dict:
    """동기식 소재 추출 태스크 실행 (외부 호출용)."""
    worker = TopicExtractWorker(db)
    return worker.run(schedule, run)

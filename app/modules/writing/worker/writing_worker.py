"""
Writing Worker - 스케줄 기반 글 생성 워커.

CrawlSchedule 설정에 따라 매일 정해진 시간에 자동으로 글을 생성합니다.

주요 기능:
    - 랜덤 3개 글 소스 믹스 글쓰기 (5회) - 쿨다운 적용
    - 랜덤 프롬프트 글쓰기 (3회) - 요소 직접 지정, 쿨다운 적용
    - 당일 슬롯 간 중복 방지
    - 시즌 기반 가중치 적용
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.models.crawl_schedule import CrawlSchedule, CrawlScheduleRun
from app.models.writing import WritingSource, GeneratedWriting
from app.models.writing_element import WritingElement
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.writing.services.element_selector import ElementSelector

logger = logging.getLogger(__name__)


@dataclass
class SlotContext:
    """당일 실행 컨텍스트 - 슬롯 간 중복 방지."""

    used_source_ids: list[int] = field(default_factory=list)
    used_topic_ids: list[int] = field(default_factory=list)
    used_keyword_ids: list[int] = field(default_factory=list)
    used_tone_ids: list[int] = field(default_factory=list)
    used_style_ids: list[int] = field(default_factory=list)
    used_format_ids: list[int] = field(default_factory=list)
    used_emotion_ids: list[int] = field(default_factory=list)

    def mark_used_sources(self, source_ids: list[int]):
        """소스 사용 기록."""
        self.used_source_ids.extend(source_ids)

    def mark_used_element(self, element: WritingElement):
        """요소 사용 기록."""
        if element.category == WritingElement.CATEGORY_TOPIC:
            self.used_topic_ids.append(element.id)
        elif element.category == WritingElement.CATEGORY_KEYWORD:
            self.used_keyword_ids.append(element.id)
        elif element.category == WritingElement.CATEGORY_TONE:
            self.used_tone_ids.append(element.id)
        elif element.category == WritingElement.CATEGORY_STYLE:
            self.used_style_ids.append(element.id)
        elif element.category == WritingElement.CATEGORY_FORMAT:
            self.used_format_ids.append(element.id)
        elif element.category == WritingElement.CATEGORY_EMOTION:
            self.used_emotion_ids.append(element.id)

    def get_exclude_ids(self, category: str) -> list[int]:
        """카테고리별 제외 ID 목록 반환."""
        mapping = {
            WritingElement.CATEGORY_TOPIC: self.used_topic_ids,
            WritingElement.CATEGORY_KEYWORD: self.used_keyword_ids,
            WritingElement.CATEGORY_TONE: self.used_tone_ids,
            WritingElement.CATEGORY_STYLE: self.used_style_ids,
            WritingElement.CATEGORY_FORMAT: self.used_format_ids,
            WritingElement.CATEGORY_EMOTION: self.used_emotion_ids,
        }
        return mapping.get(category, [])


class WritingWorker:
    """작문 워커.

    매일 정해진 시간에 실행되어:
    1. 랜덤 3개 글 믹스 → 5회 (쿨다운 + 슬롯 중복 방지)
    2. 랜덤 프롬프트 글쓰기 → 3회 (요소 직접 지정 + 쿨다운 + 시즌 가중치)
    """

    # 프롬프트 파일 경로 (프로젝트 루트 기준)
    MIX_PROMPT_PATH = Path("docs/idea/mix_prompt.md")
    RANDOM_PROMPT_PATH = Path("docs/idea/random_writing_prompt_v2.md")

    # 실행 횟수
    MIX_COUNT = 5
    RANDOM_COUNT = 3

    # LLM 타임아웃 (초)
    LLM_TIMEOUT = 180

    def __init__(self, db: Session, project_root: Optional[Path] = None):
        """WritingWorker 초기화.

        Args:
            db: SQLAlchemy 세션
            project_root: 프로젝트 루트 경로 (None이면 자동 탐지)
        """
        self.db = db
        self.llm_service = LLMService(db)
        self.selector = ElementSelector(db)

        # 프로젝트 루트 경로 설정
        if project_root:
            self.project_root = project_root
        else:
            # app/modules/writing/worker/writing_worker.py 기준
            self.project_root = Path(__file__).parent.parent.parent.parent.parent

        self._load_prompts()

    def _load_prompts(self):
        """프롬프트 파일 로드."""
        mix_path = self.project_root / self.MIX_PROMPT_PATH
        random_path = self.project_root / self.RANDOM_PROMPT_PATH

        if mix_path.exists():
            self.mix_prompt_template = mix_path.read_text(encoding="utf-8")
            logger.debug(f"Mix prompt loaded from {mix_path}")
        else:
            self.mix_prompt_template = ""
            logger.warning(f"Mix prompt not found: {mix_path}")

        if random_path.exists():
            self.random_prompt_template = random_path.read_text(encoding="utf-8")
            logger.debug(f"Random prompt loaded from {random_path}")
        else:
            self.random_prompt_template = ""
            logger.warning(f"Random prompt not found: {random_path}")

    def _get_current_season(self) -> Optional[str]:
        """현재 시즌 반환."""
        month = datetime.now().month
        day = datetime.now().day

        # 특별일 체크
        if month == 5 and 5 <= day <= 10:
            return WritingElement.SEASON_PARENTS_DAY

        # 추석 (대략적 - 실제로는 음력 계산 필요)
        if month == 9 and 10 <= day <= 20:
            return WritingElement.SEASON_CHUSEOK

        # 계절
        if month in [3, 4, 5]:
            return WritingElement.SEASON_SPRING
        elif month in [6, 7, 8]:
            return WritingElement.SEASON_SUMMER
        elif month in [9, 10, 11]:
            return WritingElement.SEASON_FALL
        else:
            return WritingElement.SEASON_WINTER

    def run(self, schedule: CrawlSchedule, run: CrawlScheduleRun) -> dict:
        """워커 실행.

        Args:
            schedule: 스케줄 설정
            run: 실행 기록

        Returns:
            {"total": 8, "success": 7, "failed": 1}
        """
        total = 0
        success = 0
        failed = 0

        logger.info(f"WritingWorker 시작: schedule_id={schedule.id}, run_id={run.id}")

        # 당일 슬롯 컨텍스트 생성
        slot_context = SlotContext()
        current_season = self._get_current_season()
        logger.info(f"현재 시즌: {current_season}")

        try:
            # 소스 글 개수 확인
            source_count = self.db.query(WritingSource).count()
            if source_count < 3:
                error_msg = f"소스 글이 부족합니다: {source_count}개 (최소 3개 필요)"
                logger.error(error_msg)
                run.mark_failed(error_msg)
                self.db.commit()
                return {"total": 0, "success": 0, "failed": 0, "error": error_msg}

            # 1. 믹스 글쓰기 (5회)
            for i in range(self.MIX_COUNT):
                logger.info(f"믹스 글쓰기 {i + 1}/{self.MIX_COUNT}")
                if self._generate_mix_writing(run.id, slot_context, index=i):
                    success += 1
                else:
                    failed += 1
                total += 1

            # 2. 랜덤 프롬프트 글쓰기 (3회)
            for i in range(self.RANDOM_COUNT):
                logger.info(f"랜덤 글쓰기 {i + 1}/{self.RANDOM_COUNT}")
                if self._generate_random_writing(run.id, slot_context, current_season, index=i):
                    success += 1
                else:
                    failed += 1
                total += 1

            # 완료 처리
            run.mark_completed(
                collected_count=total,
                saved_count=success,
                stop_reason="completed"
            )
            self.db.commit()

            logger.info(
                f"WritingWorker 완료: total={total}, success={success}, failed={failed}"
            )

        except Exception as e:
            logger.error(f"WritingWorker 실행 실패: {e}", exc_info=True)
            run.mark_failed(str(e))
            self.db.commit()
            raise

        return {"total": total, "success": success, "failed": failed}

    def _generate_mix_writing(
        self,
        run_id: int,
        slot_context: SlotContext,
        index: int = 0,
    ) -> bool:
        """믹스 글쓰기 (3개 소스 조합) - 쿨다운 및 슬롯 중복 방지 적용.

        Args:
            run_id: CrawlScheduleRun ID
            slot_context: 당일 슬롯 컨텍스트
            index: 실행 인덱스 (0부터 시작)

        Returns:
            성공 여부
        """
        llm_request = None
        try:
            # 쿨다운 + 슬롯 중복 방지 적용하여 소스 선택
            sources = self.selector.select_sources(
                count=3,
                exclude_ids=slot_context.used_source_ids,
            )

            if len(sources) < 3:
                logger.warning(f"소스가 부족합니다: {len(sources)}개")
                return False

            # 슬롯 컨텍스트에 사용 기록
            slot_context.mark_used_sources([s.id for s in sources])

            # 프롬프트 구성
            prompt = self.mix_prompt_template
            placeholders = [
                "(여기에 첫 번째 글 붙여넣기)",
                "(여기에 두 번째 글 붙여넣기)",
                "(여기에 세 번째 글 붙여넣기)",
            ]
            for placeholder, source in zip(placeholders, sources):
                prompt = prompt.replace(placeholder, source.content)

            # LLM 요청 이력 생성
            llm_request = LLMRequest(
                caller_type="writing",
                caller_id=f"mix_{run_id}_{index}",
                prompt=prompt[:5000] if len(prompt) > 5000 else prompt,
                status="processing",
                requested_by="scheduler",
                request_source="writing_worker",
            )
            self.db.add(llm_request)
            self.db.commit()
            self.db.refresh(llm_request)

            # LLM 호출 (글쓰기는 JSON이 아니라 텍스트 응답)
            result = self.llm_service.execute_claude(
                prompt, timeout=self.LLM_TIMEOUT, parse_json=False
            )

            if not result.get("success"):
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"LLM 호출 실패: {error_msg}")
                llm_request.status = "failed"
                llm_request.error_message = error_msg
                llm_request.processed_at = datetime.now()
                self.db.commit()
                return False

            # 결과 저장
            source_ids = ",".join(str(s.id) for s in sources)
            raw_response = result.get("raw_response", "")

            # LLM 요청 완료 기록
            llm_request.status = "completed"
            llm_request.raw_response = raw_response
            llm_request.processed_at = datetime.now()
            self.db.commit()

            # 생성된 글 추출
            content = self._extract_generated_content(raw_response)

            writing = GeneratedWriting(
                task_type=GeneratedWriting.TASK_TYPE_MIX,
                prompt_used=prompt[:2000] if len(prompt) > 2000 else prompt,
                source_ids=source_ids,
                content=content,
                raw_response=raw_response,
                schedule_run_id=run_id,
            )
            self.db.add(writing)
            self.db.commit()
            self.db.refresh(writing)

            # 소스 사용 이력 기록
            self.selector.record_source_usage(
                [s.id for s in sources],
                writing.id,
            )
            self.db.commit()

            logger.info(f"믹스 글쓰기 완료: id={writing.id}, sources={source_ids}")
            return True

        except Exception as e:
            logger.error(f"믹스 글쓰기 실패: {e}", exc_info=True)
            if llm_request:
                llm_request.status = "failed"
                llm_request.error_message = str(e)
                llm_request.processed_at = datetime.now()
                self.db.commit()
            else:
                self.db.rollback()
            return False

    def _generate_random_writing(
        self,
        run_id: int,
        slot_context: SlotContext,
        season: Optional[str],
        index: int = 0,
    ) -> bool:
        """랜덤 프롬프트 글쓰기 - 요소 직접 지정, 쿨다운 및 시즌 가중치 적용.

        Args:
            run_id: CrawlScheduleRun ID
            slot_context: 당일 슬롯 컨텍스트
            season: 현재 시즌
            index: 실행 인덱스 (0부터 시작)

        Returns:
            성공 여부
        """
        llm_request = None
        try:
            if not self.random_prompt_template:
                logger.error("랜덤 프롬프트가 없습니다")
                return False

            # 요소 선택 (쿨다운 + 슬롯 중복 방지 + 시즌 가중치)
            selected_elements = self._select_random_elements(slot_context, season)

            if not selected_elements:
                logger.error("요소 선택 실패")
                return False

            # 슬롯 컨텍스트에 사용 기록
            for elem in selected_elements["all"]:
                slot_context.mark_used_element(elem)

            # 프롬프트 구성 (요소 직접 지정)
            prompt = self.random_prompt_template.format(
                topic=selected_elements["topic"].name,
                keywords=", ".join(k.name for k in selected_elements["keywords"]),
                tone=selected_elements["tone"].name,
                style=selected_elements["style"].name,
                format=selected_elements["format"].name,
                emotion=selected_elements["emotion"].name,
            )

            # LLM 요청 이력 생성
            llm_request = LLMRequest(
                caller_type="writing",
                caller_id=f"random_{run_id}_{index}",
                prompt=prompt[:5000] if len(prompt) > 5000 else prompt,
                status="processing",
                requested_by="scheduler",
                request_source="writing_worker",
            )
            self.db.add(llm_request)
            self.db.commit()
            self.db.refresh(llm_request)

            # LLM 호출
            result = self.llm_service.execute_claude(
                prompt, timeout=self.LLM_TIMEOUT, parse_json=False
            )

            if not result.get("success"):
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"LLM 호출 실패: {error_msg}")
                llm_request.status = "failed"
                llm_request.error_message = error_msg
                llm_request.processed_at = datetime.now()
                self.db.commit()
                return False

            raw_response = result.get("raw_response", "")

            # LLM 요청 완료 기록
            llm_request.status = "completed"
            llm_request.raw_response = raw_response
            llm_request.processed_at = datetime.now()
            self.db.commit()

            content = self._extract_generated_content(raw_response)

            # selected_elements JSON 생성
            selected_json = json.dumps({
                "topic": selected_elements["topic"].name,
                "keywords": [k.name for k in selected_elements["keywords"]],
                "tone": selected_elements["tone"].name,
                "style": selected_elements["style"].name,
                "format": selected_elements["format"].name,
                "emotion": selected_elements["emotion"].name,
                "season": season,
            }, ensure_ascii=False)

            writing = GeneratedWriting(
                task_type=GeneratedWriting.TASK_TYPE_RANDOM,
                prompt_used=prompt[:2000] if len(prompt) > 2000 else prompt,
                source_ids=None,
                content=content,
                raw_response=raw_response,
                selected_elements=selected_json,
                schedule_run_id=run_id,
            )
            self.db.add(writing)
            self.db.commit()
            self.db.refresh(writing)

            # 요소 사용 이력 기록
            self.selector.record_element_usage(
                selected_elements["all"],
                writing.id,
            )
            self.db.commit()

            logger.info(
                f"랜덤 글쓰기 완료: id={writing.id}, "
                f"topic={selected_elements['topic'].name}, season={season}"
            )
            return True

        except Exception as e:
            logger.error(f"랜덤 글쓰기 실패: {e}", exc_info=True)
            if llm_request:
                llm_request.status = "failed"
                llm_request.error_message = str(e)
                llm_request.processed_at = datetime.now()
                self.db.commit()
            else:
                self.db.rollback()
            return False

    def _select_random_elements(
        self,
        slot_context: SlotContext,
        season: Optional[str],
    ) -> Optional[dict]:
        """Random Writing용 요소 선택.

        Args:
            slot_context: 당일 슬롯 컨텍스트
            season: 현재 시즌

        Returns:
            {"topic": WritingElement, "keywords": [...], "all": [...]}
        """
        try:
            # 각 카테고리에서 요소 선택
            topic = self.selector.select_element(
                WritingElement.CATEGORY_TOPIC,
                exclude_ids=slot_context.get_exclude_ids(WritingElement.CATEGORY_TOPIC),
                season=season,
            )
            keywords = self.selector.select_elements(
                WritingElement.CATEGORY_KEYWORD,
                count=2,
                exclude_ids=slot_context.get_exclude_ids(WritingElement.CATEGORY_KEYWORD),
                season=season,
            )
            tone = self.selector.select_element(
                WritingElement.CATEGORY_TONE,
                exclude_ids=slot_context.get_exclude_ids(WritingElement.CATEGORY_TONE),
                season=season,
            )
            style = self.selector.select_element(
                WritingElement.CATEGORY_STYLE,
                exclude_ids=slot_context.get_exclude_ids(WritingElement.CATEGORY_STYLE),
            )
            fmt = self.selector.select_element(
                WritingElement.CATEGORY_FORMAT,
                exclude_ids=slot_context.get_exclude_ids(WritingElement.CATEGORY_FORMAT),
            )
            emotion = self.selector.select_element(
                WritingElement.CATEGORY_EMOTION,
                exclude_ids=slot_context.get_exclude_ids(WritingElement.CATEGORY_EMOTION),
                season=season,
            )

            # 필수 요소 체크
            if not all([topic, tone, style, fmt, emotion]) or len(keywords) < 2:
                logger.error("필수 요소 선택 실패")
                return None

            all_elements = [topic, tone, style, fmt, emotion] + keywords

            return {
                "topic": topic,
                "keywords": keywords,
                "tone": tone,
                "style": style,
                "format": fmt,
                "emotion": emotion,
                "all": all_elements,
            }

        except Exception as e:
            logger.error(f"요소 선택 실패: {e}", exc_info=True)
            return None

    def _extract_generated_content(self, raw_response: str) -> str:
        """LLM 응답에서 생성된 글 추출.

        프롬프트 구조상 분석 후 실제 글이 나오므로,
        마지막 큰 문단을 추출합니다.

        Args:
            raw_response: LLM 원본 응답

        Returns:
            추출된 글 내용
        """
        if not raw_response:
            return ""

        # --- 구분자가 있으면 이후 내용 추출
        if "---" in raw_response:
            parts = raw_response.split("---")
            # 마지막 non-empty 파트 중 충분히 긴 것
            for part in reversed(parts):
                stripped = part.strip()
                if stripped and len(stripped) > 100:
                    return stripped

        return raw_response.strip()


def run_writing_task_sync(
    db: Session,
    schedule: CrawlSchedule,
    run: CrawlScheduleRun,
    project_root: Optional[Path] = None,
) -> dict:
    """동기식 작문 태스크 실행 (외부 호출용).

    Args:
        db: SQLAlchemy 세션
        schedule: 스케줄 설정
        run: 실행 기록
        project_root: 프로젝트 루트 경로

    Returns:
        실행 결과 dict
    """
    worker = WritingWorker(db, project_root)
    return worker.run(schedule, run)

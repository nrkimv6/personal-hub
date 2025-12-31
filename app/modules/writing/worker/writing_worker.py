"""
Writing Worker - 스케줄 기반 글 생성 워커.

CrawlSchedule 설정에 따라 매일 정해진 시간에 자동으로 글을 생성합니다.

주요 기능:
    - 랜덤 3개 글 소스 믹스 글쓰기 (5회)
    - 랜덤 프롬프트 글쓰기 (3회)
    - 생성된 글 저장 및 관리
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.crawl_schedule import CrawlSchedule, CrawlScheduleRun
from app.models.writing import WritingSource, GeneratedWriting
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.models.llm_request import LLMRequest

logger = logging.getLogger(__name__)


class WritingWorker:
    """작문 워커.

    매일 정해진 시간에 실행되어:
    1. 랜덤 3개 글 믹스 → 5회
    2. 랜덤 프롬프트 글쓰기 → 3회
    """

    # 프롬프트 파일 경로 (프로젝트 루트 기준)
    MIX_PROMPT_PATH = Path("docs/idea/mix_prompt.md")
    RANDOM_PROMPT_PATH = Path("docs/idea/random_writing_prompt.md")

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
                if self._generate_mix_writing(run.id, index=i):
                    success += 1
                else:
                    failed += 1
                total += 1

            # 2. 랜덤 프롬프트 글쓰기 (3회)
            for i in range(self.RANDOM_COUNT):
                logger.info(f"랜덤 글쓰기 {i + 1}/{self.RANDOM_COUNT}")
                if self._generate_random_writing(run.id, index=i):
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

    def _generate_mix_writing(self, run_id: int, index: int = 0) -> bool:
        """믹스 글쓰기 (3개 소스 조합).

        Args:
            run_id: CrawlScheduleRun ID
            index: 실행 인덱스 (0부터 시작)

        Returns:
            성공 여부
        """
        llm_request = None
        try:
            # 랜덤 3개 소스 선택
            sources = (
                self.db.query(WritingSource)
                .order_by(func.random())
                .limit(3)
                .all()
            )

            if len(sources) < 3:
                logger.warning(f"소스가 부족합니다: {len(sources)}개")
                return False

            # 프롬프트 구성
            prompt = self.mix_prompt_template
            placeholders = [
                "(여기에 첫 번째 글 붙여넣기)",
                "(여기에 두 번째 글 붙여넣기)",
                "(여기에 세 번째 글 붙여넣기)",
            ]
            for i, (placeholder, source) in enumerate(zip(placeholders, sources)):
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
                # LLM 요청 실패 기록
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

            logger.info(f"믹스 글쓰기 완료: id={writing.id}")
            return True

        except Exception as e:
            logger.error(f"믹스 글쓰기 실패: {e}", exc_info=True)
            # LLM 요청 실패 기록
            if llm_request:
                llm_request.status = "failed"
                llm_request.error_message = str(e)
                llm_request.processed_at = datetime.now()
                self.db.commit()
            else:
                self.db.rollback()
            return False

    def _generate_random_writing(self, run_id: int, index: int = 0) -> bool:
        """랜덤 프롬프트 글쓰기.

        Args:
            run_id: CrawlScheduleRun ID
            index: 실행 인덱스 (0부터 시작)

        Returns:
            성공 여부
        """
        llm_request = None
        try:
            prompt = self.random_prompt_template

            if not prompt:
                logger.error("랜덤 프롬프트가 없습니다")
                return False

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

            # LLM 호출 (글쓰기는 JSON이 아니라 텍스트 응답)
            result = self.llm_service.execute_claude(
                prompt, timeout=self.LLM_TIMEOUT, parse_json=False
            )

            if not result.get("success"):
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"LLM 호출 실패: {error_msg}")
                # LLM 요청 실패 기록
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

            writing = GeneratedWriting(
                task_type=GeneratedWriting.TASK_TYPE_RANDOM,
                prompt_used=prompt[:2000] if len(prompt) > 2000 else prompt,
                source_ids=None,
                content=content,
                raw_response=raw_response,
                schedule_run_id=run_id,
            )
            self.db.add(writing)
            self.db.commit()

            logger.info(f"랜덤 글쓰기 완료: id={writing.id}")
            return True

        except Exception as e:
            logger.error(f"랜덤 글쓰기 실패: {e}", exc_info=True)
            # LLM 요청 실패 기록
            if llm_request:
                llm_request.status = "failed"
                llm_request.error_message = str(e)
                llm_request.processed_at = datetime.now()
                self.db.commit()
            else:
                self.db.rollback()
            return False

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

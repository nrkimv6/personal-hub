"""
plan_analyze_handler.py — Plan Archive LLM 분석 핸들러

archive된 plan 파일을 LLM으로 분석하여 category/tags/summary를 추출하고
plan_records 테이블에 저장한다.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from sqlalchemy.orm import Session

from app.models.plan_record import PlanRecord

logger = logging.getLogger(__name__)


def save_plan_archive_result(db: Session, request, result: dict) -> None:
    """plan_archive_analyze caller_type 결과 저장

    LLM 결과에서 category, tags, summary, superseded_by 추출 →
    plan_records 테이블 UPDATE (filename_hash = request.caller_id)

    Args:
        db: SQLAlchemy Session
        request: LLMRequest 인스턴스
        result: {"success": bool, "result": dict, "raw_response": str}
    """
    try:
        filename_hash = request.caller_id
        record = db.query(PlanRecord).filter_by(filename_hash=filename_hash).first()
        if not record:
            logger.error(f"save_plan_archive_result: record not found for hash={filename_hash}")
            return

        llm_result = result.get("result") or {}

        if isinstance(llm_result, str):
            try:
                llm_result = json.loads(llm_result)
            except Exception:
                llm_result = {}

        category = llm_result.get("category")
        tags = llm_result.get("tags")
        summary = llm_result.get("summary")
        superseded_by = llm_result.get("superseded_by")

        if category:
            record.category = category
        if tags is not None:
            record.tags = tags if isinstance(tags, list) else [tags]
        if summary:
            record.summary = summary
        if superseded_by:
            record.superseded_by = superseded_by

        record.llm_processed_at = datetime.now()
        record.updated_at = datetime.now()
        db.commit()
        logger.info(f"save_plan_archive_result: updated record id={record.id} category={category}")
    except Exception as e:
        logger.error(f"save_plan_archive_result error: {e}", exc_info=True)


def save_requirements_sync_result(db: Session, request, result: dict) -> None:
    """plan_requirements_sync caller_type 결과 저장

    LLM 결과에서 요구사항 텍스트 추출 →
    docs/requirements/{category}.md 파일 생성/갱신

    Args:
        db: SQLAlchemy Session
        request: LLMRequest 인스턴스
        result: {"success": bool, "result": dict, "raw_response": str}
    """
    try:
        llm_result = result.get("result") or {}
        if isinstance(llm_result, str):
            try:
                llm_result = json.loads(llm_result)
            except Exception:
                llm_result = {}

        category = llm_result.get("category") or request.caller_id
        requirements_text = llm_result.get("requirements") or result.get("raw_response", "")

        if not requirements_text:
            logger.warning(f"save_requirements_sync_result: empty requirements for category={category}")
            return

        # docs/requirements/ 디렉토리 생성
        from pathlib import Path
        base_dir = Path(__file__).parent.parent.parent.parent  # monitor-page root
        req_dir = base_dir / "docs" / "requirements"
        req_dir.mkdir(parents=True, exist_ok=True)

        req_file = req_dir / f"{category}.md"
        req_file.write_text(requirements_text, encoding="utf-8")
        logger.info(f"save_requirements_sync_result: written {req_file}")
    except Exception as e:
        logger.error(f"save_requirements_sync_result error: {e}", exc_info=True)


def build_plan_analyze_prompt(
    file_content: str,
    filename: str,
    existing_categories: Optional[List[str]] = None
) -> str:
    """plan archive 분석 프롬프트 생성

    Args:
        file_content: plan 파일 내용
        filename: 파일명 (날짜/컨텍스트 추출용)
        existing_categories: 기존 카테고리 목록 (분류 일관성 유지)

    Returns:
        LLM에 전달할 프롬프트 문자열
    """
    if existing_categories is None:
        existing_categories = [
            "naver-booking", "instagram", "google-search", "activity",
            "claude-worker", "video", "infra", "writing", "common"
        ]

    categories_str = ", ".join(existing_categories)

    prompt = f"""다음은 개발 프로젝트의 plan 파일입니다. 파일명: {filename}

아래 내용을 분석하여 JSON 형식으로 결과를 반환해주세요.

**파일 내용:**
{file_content[:3000]}

**출력 JSON 스키마:**
{{
  "category": "모듈 카테고리 (다음 중 하나: {categories_str}, 또는 적절한 새 카테고리)",
  "tags": ["feat", "fix", "refactor", "chore", "docs", "test"] 중 해당하는 것들,
  "summary": "이 plan의 핵심 내용을 2-3문장으로 요약",
  "superseded_by": "이 plan을 대체하는 더 최신 plan 파일명 (없으면 null)"
}}

JSON만 출력하세요. 다른 설명은 불필요합니다."""
    return prompt


def build_requirements_sync_prompt(category: str, plan_summaries: List[dict]) -> str:
    """요구사항 문서 생성 프롬프트

    Args:
        category: 카테고리명
        plan_summaries: [{"filename": str, "summary": str, "tags": list, "date": str}, ...]

    Returns:
        LLM에 전달할 프롬프트 문자열
    """
    summaries_text = "\n".join([
        f"- [{s.get('date', '')}] {s.get('filename', '')}: {s.get('summary', '')}"
        for s in plan_summaries
    ])

    prompt = f"""다음은 '{category}' 모듈의 개발 히스토리입니다.

{summaries_text}

위 히스토리를 바탕으로 이 모듈의 **기능 요구사항 문서**를 Markdown 형식으로 작성해주세요.

**출력 JSON 스키마:**
{{
  "category": "{category}",
  "requirements": "# {category} 요구사항\\n\\n## 주요 기능\\n...\\n## 이력\\n..."
}}

JSON만 출력하세요."""
    return prompt

"""
plan_analyze_handler.py — Plan Archive LLM 분석 핸들러

archive된 plan 파일을 LLM으로 분석하여 category/tags/summary를 추출하고
plan_records 테이블에 저장한다.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

from sqlalchemy.orm import Session

from app.core.database import is_connection_error
from app.models.plan_record import PlanRecord
from app.modules.claude_worker.services.llm_service import LLMService

logger = logging.getLogger(__name__)


def save_plan_archive_result(db: Session, request, result: dict) -> bool:
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
            return False

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

        intent = llm_result.get("intent")
        trigger_val = llm_result.get("trigger")
        scope = llm_result.get("scope")
        if intent:
            record.intent = intent
        if trigger_val:
            record.trigger = trigger_val
        if scope is not None:
            record.scope = json.dumps(scope, ensure_ascii=False) if isinstance(scope, list) else scope

        if not record.raw_content and record.file_path:
            try:
                content = Path(record.file_path).read_text(encoding="utf-8")
                record.raw_content = content
            except Exception:
                pass

        now = datetime.now()
        record.llm_processed_at = now
        if record.raw_content:
            record.file_delete_after = now + timedelta(days=7)
        else:
            record.file_delete_after = None
        record.updated_at = now
        db.commit()
        logger.info(f"save_plan_archive_result: updated record id={record.id} category={category}")

        # dev-guide staleness 자동 감지
        _maybe_flag_guide_staleness(db, record.file_path)

        # 반복 감지 트리거
        if record.intent and record.scope:
            detect_recurrence(db, record)
        
        return True
    except Exception as e:
        if is_connection_error(e):
            logger.warning("save_plan_archive_result connection error: %s", e)
        else:
            logger.error(f"save_plan_archive_result error: {e}", exc_info=True)
        db.rollback()
        return False


def build_devguide_staleness_report(db: Session) -> list:
    """dev-guide staleness 리포트 생성.

    PlanRecordService.get_guide_status()로 가이드별 pending_count 조회 →
    pending > 0인 가이드만 필터.

    Returns:
        [{guide, pending_count, pending_archives: [{file_path, summary}]}]
    """
    try:
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService
        statuses = PlanRecordService(db).get_guide_status()
        return [
            {
                "guide": s["guide"],
                "pending_count": s["pending_count"],
                "pending_archives": [
                    {"file_path": a["file_path"], "summary": a["summary"]}
                    for a in s.get("pending_archives", [])
                ],
            }
            for s in statuses
            if s.get("pending_count", 0) > 0
        ]
    except Exception as e:
        if is_connection_error(e):
            logger.warning("build_devguide_staleness_report connection error: %s", e)
        else:
            logger.error(f"build_devguide_staleness_report error: {e}", exc_info=True)
        return []


def save_devguide_staleness_result(db: Session, report: list) -> bool:
    """dev-guide staleness 리포트를 PlanEvent로 저장.

    Args:
        db: SQLAlchemy Session
        report: build_devguide_staleness_report() 반환값
    """
    try:
        from app.models.plan_record import PlanEvent
        event = PlanEvent(
            plan_record_id=None,  # 시스템 이벤트 — plan_record_id nullable 허용
            event_type="devguide_staleness",
            detail={"guides": report},
        )
        db.add(event)
        db.commit()
        logger.info(f"save_devguide_staleness_result: saved event with {len(report)} guides")
        return True
    except Exception as e:
        if is_connection_error(e):
            logger.warning("save_devguide_staleness_result connection error: %s", e)
        else:
            logger.error(f"save_devguide_staleness_result error: {e}", exc_info=True)
        db.rollback()
        return False


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
  "superseded_by": "이 plan을 대체하는 더 최신 plan 파일명 (없으면 null)",
  "intent": "이 plan이 해결하려는 핵심 문제 (1-2문장)",
  "trigger": "bug_recurrence|new_feature|refactor|ux_improvement|infra|unknown 중 하나",
  "scope": ["영향받는 모듈/파일/기능을 배열로 추출, 예: \"naver-booking\", \"plan_service.py\""]
}}

JSON만 출력하세요. 다른 설명은 불필요합니다."""
    return prompt

def _maybe_flag_guide_staleness(db: Session, file_path: str) -> bool:
    """archive 분석 완료 후 관련 가이드의 staleness 자동 감지.

    file_path의 태그와 meta.yaml의 owns_archive_tags 교차 →
    pending_count >= THRESHOLD 시 PlanEvent(devguide_staleness) 생성.

    Args:
        db: SQLAlchemy Session
        file_path: 방금 archive된 plan 파일 경로

    Returns:
        True if PlanEvent가 새로 생성됨, False otherwise
    """
    THRESHOLD = 3
    try:
        from app.shared.wiki_tags import extract_wiki_tags, load_whitelist, load_meta_yaml
        from app.models.plan_record import PlanEvent
        from pathlib import Path as _Path
        from sqlalchemy import and_

        whitelist = load_whitelist()
        meta = load_meta_yaml()
        tags = set(extract_wiki_tags(_Path(file_path).name, whitelist))

        created = False
        for guide_name, guide_meta in meta.items():
            owns = set(guide_meta.get("owns_archive_tags") or [])
            if not (tags & owns):
                continue
            last_scan_str = guide_meta.get("last_archive_scan") or ""
            try:
                from datetime import datetime as _dt
                last_scan = _dt.strptime(last_scan_str, "%Y-%m-%d") if last_scan_str else None
            except ValueError:
                last_scan = None

            if not last_scan:
                continue

            # pending_count 계산: last_scan 이후 archived_at AND 태그 매칭
            records = db.query(PlanRecord).filter(
                and_(
                    PlanRecord.archived_at.isnot(None),
                    PlanRecord.archived_at > last_scan,
                )
            ).all()
            pending_count = 0
            for rec in records:
                fname = _Path(rec.file_path).name
                rtags = set(extract_wiki_tags(fname, whitelist))
                if rtags & owns:
                    pending_count += 1

            if pending_count >= THRESHOLD:
                event = PlanEvent(
                    plan_record_id=None,
                    event_type="devguide_staleness",
                    detail={"guide": guide_name, "pending_count": pending_count},
                )
                db.add(event)
                db.commit()
                logger.info(f"_maybe_flag_guide_staleness: flagged guide={guide_name} pending={pending_count}")
                created = True
        return created
    except Exception as e:
        if is_connection_error(e):
            logger.warning("_maybe_flag_guide_staleness connection error: %s", e)
        else:
            logger.error(f"_maybe_flag_guide_staleness error: {e}", exc_info=True)
        return False


# ──────────────────────────────────────────────
# Phase 2: 반복 감지 로직
# ──────────────────────────────────────────────

def _get_scope_overlap_candidates(db: Session, record: PlanRecord) -> list:
    """scope 겹침 후보 레코드 반환 (최대 20개)

    같은 category + scope IS NOT NULL + applied_at IS NOT NULL + 자기 자신 제외
    → Python set 교집합으로 필터 → applied_at 기준 plan_date와 가까운 순 정렬
    """
    try:
        from sqlalchemy import and_

        record_scope = set(json.loads(record.scope or "[]"))
        if not record_scope:
            return []

        candidates = db.query(PlanRecord).filter(
            and_(
                PlanRecord.category == record.category,
                PlanRecord.scope.isnot(None),
                PlanRecord.applied_at.isnot(None),
                PlanRecord.filename_hash != record.filename_hash,
            )
        ).limit(50).all()

        # Python 레벨 set 교집합 필터
        overlapping = [
            c for c in candidates
            if set(json.loads(c.scope or "[]")) & record_scope
        ]

        # applied_at 기준 record.plan_date와 가까운 순 정렬, 180일 이내 우선
        from datetime import date, timedelta

        def sort_key(c):
            if record.plan_date and c.applied_at:
                delta = abs((c.applied_at.date() - record.plan_date).days)
                return (0 if delta <= 180 else 1, delta)
            return (2, 0)

        overlapping.sort(key=sort_key)
        return overlapping[:20]
    except Exception as e:
        if is_connection_error(e):
            logger.warning("_get_scope_overlap_candidates connection error: %s", e)
        else:
            logger.error(f"_get_scope_overlap_candidates error: {e}", exc_info=True)
        return []


def detect_recurrence(db: Session, record: PlanRecord) -> bool:
    """반복 감지: scope 겹침 후보 있으면 LLM 큐 등록

    Returns:
        True if LLM 큐 등록됨, False otherwise
    """
    try:
        from app.modules.claude_worker.models.llm_request import LLMRequest
        from sqlalchemy import and_

        candidates = _get_scope_overlap_candidates(db, record)
        if not candidates:
            return False

        # 중복 방지: 같은 caller_id + status in (pending, processing)
        existing = db.query(LLMRequest).filter(
            and_(
                LLMRequest.caller_type == "plan_recurrence_check",
                LLMRequest.caller_id == record.filename_hash,
                LLMRequest.status.in_(["pending", "processing"]),
            )
        ).first()
        if existing:
            logger.info(f"detect_recurrence: 이미 pending/processing 요청 있음 hash={record.filename_hash[:8]}")
            return False

        prompt = build_recurrence_check_prompt(record, candidates)
        llm_service = LLMService(db)
        provider, model = llm_service.resolve_provider_model(
            caller_type="plan_recurrence_check",
            provider=None,
            model=None,
        )
        llm_req = LLMRequest(
            caller_type="plan_recurrence_check",
            caller_id=record.filename_hash,
            prompt=prompt,
            queue_name="utility",
            requested_by="scheduler",
            provider=provider,
            model=model,
        )
        db.add(llm_req)
        db.commit()
        logger.info(f"detect_recurrence: LLM 큐 등록 hash={record.filename_hash[:8]}")
        return True
    except Exception as e:
        if is_connection_error(e):
            logger.warning("detect_recurrence connection error: %s", e)
        else:
            logger.error(f"detect_recurrence error: {e}", exc_info=True)
        return False


def build_recurrence_check_prompt(record: PlanRecord, candidates: list) -> str:
    """반복 감지 LLM 프롬프트 생성

    Returns:
        JSON 출력 스키마: {"is_recurrence": bool, "matched_hash": str|null,
                          "confidence": "high"|"medium"|"low", "reason": str}
    """
    from datetime import date

    current_scope = json.loads(record.scope or "[]") if record.scope else []
    plan_date_str = str(record.plan_date) if record.plan_date else "unknown"

    candidates_text = ""
    for c in candidates[:10]:  # 최대 10개만
        c_scope = json.loads(c.scope or "[]") if c.scope else []
        applied_str = c.applied_at.strftime("%Y-%m-%d") if c.applied_at else "unknown"
        delta_days = ""
        if record.plan_date and c.applied_at:
            delta_days = f" ({abs((c.applied_at.date() - record.plan_date).days)}일 전)"
        candidates_text += f"""
- hash: {c.filename_hash}
  intent: {c.intent or '(없음)'}
  scope: {c_scope}
  applied_at: {applied_str}{delta_days}
"""

    prompt = f"""다음 두 개발 계획을 비교하여 반복 수정 여부를 판단하세요.

## 현재 계획
- plan_date: {plan_date_str}
- intent: {record.intent}
- scope: {current_scope}

## 이전 관련 계획 후보
{candidates_text}

반복 수정이란: 동일하거나 매우 유사한 문제를 다시 수정하는 것을 의미합니다.
scope 겹침이 있더라도 intent가 완전히 다른 문제라면 is_recurrence=false입니다.

**출력 JSON 스키마 (JSON만 출력):**
{{
  "is_recurrence": true | false,
  "matched_hash": "가장 유사한 이전 계획의 filename_hash (없으면 null)",
  "confidence": "high" | "medium" | "low",
  "reason": "판단 근거 1-2문장"
}}"""
    return prompt


def save_recurrence_check_result(db: Session, request, result: dict) -> bool:
    """plan_recurrence_check caller_type 결과 저장

    is_recurrence=True 시 superseded_by, chain_root_hash, recurrence_count 설정
    """
    try:
        filename_hash = request.caller_id
        record = db.query(PlanRecord).filter_by(filename_hash=filename_hash).first()
        if not record:
            logger.error(f"save_recurrence_check_result: record not found hash={filename_hash}")
            return False

        llm_result = result.get("result") or {}
        if isinstance(llm_result, str):
            try:
                llm_result = json.loads(llm_result)
            except Exception:
                llm_result = {}

        is_recurrence = llm_result.get("is_recurrence", False)
        matched_hash = llm_result.get("matched_hash")

        if is_recurrence and matched_hash:
            matched_record = db.query(PlanRecord).filter_by(filename_hash=matched_hash).first()
            if matched_record:
                record.superseded_by = matched_hash

                # chain_root_hash 전파
                if matched_record.chain_root_hash:
                    record.chain_root_hash = matched_record.chain_root_hash
                else:
                    record.chain_root_hash = matched_hash

                # recurrence_count 증가
                matched_count = matched_record.recurrence_count or 1
                record.recurrence_count = matched_count + 1

                record.updated_at = datetime.now()
                db.commit()
                logger.info(
                    f"save_recurrence_check_result: linked hash={filename_hash[:8]} "
                    f"→ matched={matched_hash[:8]}, count={record.recurrence_count}"
                )

                # AI 제안 큐 등록 시도
                maybe_queue_recurrence_suggest(db, record)
            else:
                logger.warning(f"save_recurrence_check_result: matched_record not found hash={matched_hash}")
        else:
            logger.info(f"save_recurrence_check_result: no recurrence detected hash={filename_hash[:8]}")
        
        return True
    except Exception as e:
        if is_connection_error(e):
            logger.warning("save_recurrence_check_result connection error: %s", e)
        else:
            logger.error(f"save_recurrence_check_result error: {e}", exc_info=True)
        db.rollback()
        return False


# ──────────────────────────────────────────────
# Phase 3: AI 제안 생성
# ──────────────────────────────────────────────

def maybe_queue_recurrence_suggest(db: Session, record: PlanRecord) -> bool:
    """recurrence_count >= 2 조건 시 AI 제안 LLM 큐 등록

    Returns:
        True if LLM 큐 등록됨, False otherwise
    """
    try:
        if (record.recurrence_count or 1) < 2:
            return False

        from app.modules.claude_worker.models.llm_request import LLMRequest
        from sqlalchemy import and_
        from datetime import timedelta

        chain_root = record.chain_root_hash
        if not chain_root:
            return False

        # 24시간 내 중복 요청 확인
        cutoff = datetime.now() - timedelta(hours=24)
        existing = db.query(LLMRequest).filter(
            and_(
                LLMRequest.caller_type == "plan_recurrence_suggest",
                LLMRequest.caller_id == chain_root,
                LLMRequest.requested_at > cutoff,
                LLMRequest.status.in_(["pending", "processing"]),
            )
        ).first()
        if existing:
            logger.info(f"maybe_queue_recurrence_suggest: 24h 내 중복 스킵 root={chain_root[:8]}")
            return False

        # 체인 전체 조회 (recurrence_count 오름차순)
        chain_records = db.query(PlanRecord).filter(
            and_(
                PlanRecord.chain_root_hash == chain_root,
            )
        ).order_by(PlanRecord.recurrence_count.asc()).all()

        # chain root 자체도 포함
        root_record = db.query(PlanRecord).filter_by(filename_hash=chain_root).first()
        if root_record and root_record not in chain_records:
            chain_records = [root_record] + chain_records

        prompt = build_recurrence_suggest_prompt(chain_records)
        llm_service = LLMService(db)
        provider, model = llm_service.resolve_provider_model(
            caller_type="plan_recurrence_suggest",
            provider=None,
            model=None,
        )
        llm_req = LLMRequest(
            caller_type="plan_recurrence_suggest",
            caller_id=chain_root,
            prompt=prompt,
            queue_name="utility",
            requested_by="scheduler",
            provider=provider,
            model=model,
        )
        db.add(llm_req)
        db.commit()
        logger.info(f"maybe_queue_recurrence_suggest: LLM 큐 등록 root={chain_root[:8]}")
        return True
    except Exception as e:
        if is_connection_error(e):
            logger.warning("maybe_queue_recurrence_suggest connection error: %s", e)
        else:
            logger.error(f"maybe_queue_recurrence_suggest error: {e}", exc_info=True)
        return False


def build_recurrence_suggest_prompt(chain_records: list) -> str:
    """반복 수정 근본원인 분석 + 개선 제안 프롬프트 생성

    Returns:
        JSON 출력 스키마: {"root_cause": str, "pattern": str, "suggestion": str, "recurrence_count": int}
    """
    records_text = ""
    for r in chain_records:
        scope_list = json.loads(r.scope or "[]") if r.scope else []
        plan_date_str = str(r.plan_date) if r.plan_date else "unknown"
        applied_str = r.applied_at.strftime("%Y-%m-%d") if r.applied_at else "미완료"
        records_text += f"""
- 반복 {r.recurrence_count}회: plan_date={plan_date_str}, applied_at={applied_str}
  intent: {r.intent or '(없음)'}
  scope: {scope_list}
  trigger: {r.trigger or 'unknown'}
"""

    prompt = f"""다음은 동일한 모듈/기능을 반복 수정한 개발 이력입니다. (총 {len(chain_records)}회)

{records_text}

이 반복 수정 패턴을 분석하여 근본 원인과 개선 방향을 제시해주세요.

**출력 JSON 스키마 (JSON만 출력):**
{{
  "root_cause": "반복 수정의 근본 원인 (2-3문장)",
  "pattern": "반복되는 패턴 설명 (1-2문장)",
  "suggestion": "재발 방지를 위한 구체적 개선 방향 (2-3문장)",
  "recurrence_count": {len(chain_records)}
}}"""
    return prompt


def save_recurrence_suggest_result(db: Session, request, result: dict) -> bool:
    """plan_recurrence_suggest caller_type 결과 저장

    chain_root_hash 기준으로 recurrence_count 가장 높은 record에 저장
    """
    try:
        chain_root = request.caller_id

        # recurrence_count 가장 높은 record 조회
        from sqlalchemy import and_

        latest_record = db.query(PlanRecord).filter(
            and_(
                PlanRecord.chain_root_hash == chain_root,
            )
        ).order_by(PlanRecord.recurrence_count.desc()).first()

        if not latest_record:
            # chain root 자체를 대상으로
            latest_record = db.query(PlanRecord).filter_by(filename_hash=chain_root).first()

        if not latest_record:
            logger.error(f"save_recurrence_suggest_result: no record found for root={chain_root}")
            return False

        llm_result = result.get("result") or {}
        if isinstance(llm_result, str):
            try:
                llm_result = json.loads(llm_result)
            except Exception:
                llm_result = {}

        suggestion_data = {
            "root_cause": llm_result.get("root_cause", ""),
            "pattern": llm_result.get("pattern", ""),
            "suggestion": llm_result.get("suggestion", ""),
        }
        latest_record.recurrence_suggestion = json.dumps(suggestion_data, ensure_ascii=False)
        latest_record.updated_at = datetime.now()
        db.commit()
        logger.info(f"save_recurrence_suggest_result: saved for record id={latest_record.id}")
        return True
    except Exception as e:
        if is_connection_error(e):
            logger.warning("save_recurrence_suggest_result connection error: %s", e)
        else:
            logger.error(f"save_recurrence_suggest_result error: {e}", exc_info=True)
        db.rollback()
        return False

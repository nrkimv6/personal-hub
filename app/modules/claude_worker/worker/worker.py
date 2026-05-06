"""
Claude LLM 워커 프로세스

API 서버와 분리되어 독립적으로 LLM 작업을 수행합니다.

실행 방법:
    python -m app.modules.claude_worker.worker.worker

주요 기능:
    - Pending LLM 요청 처리
    - Claude CLI subprocess 실행
    - 결과 파싱 및 저장
    - caller_type별 결과 저장 (instagram -> instagram_posts)
"""
import asyncio
import json
import sys
import os
import signal
import logging
import time
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# 비동기 로거 설정
from app.utils.async_logger import AsyncLoggerManager
from app.shared.llm_registry import report_quota as _registry_report_quota
from app.modules.claude_worker.services import provider_registry
from app.modules.claude_worker.services.executors.base import normalize_json_payload

# 워커 전용 비동기 로거 설정
logger = AsyncLoggerManager.setup_worker_logger(
    log_prefix="llm_worker",
    log_dir=Path("logs"),
    level=logging.DEBUG
)
logger.info(f"LLM 워커 비동기 로거 초기화 완료 - 로그 파일: {logger.log_file}")

# 모듈 import
try:
    logger.info("모듈 import 시작...")

    from app.database import SessionLocal
    logger.debug("app.database import 완료")

    from app.modules.claude_worker.models.llm_request import LLMRequest
    logger.debug("llm_request 모델 import 완료")

    # WritingBatch 모델 import (LLMRequest의 외래키 참조를 위해 필요)
    from app.modules.writing.models.writing_batch import WritingBatch
    logger.debug("writing_batch 모델 import 완료")

    from app.modules.claude_worker.services.llm_service import LLMService
    logger.debug("llm_service import 완료")

    from app.modules.claude_worker.services.execution_window_service import (
        LLMExecutionWindowService,
        max_resume_at,
    )
    logger.debug("execution_window_service import 완료")

    from app.modules.claude_worker.services.plan_analyze_handler import (
        save_plan_archive_result_outcome,
        save_recurrence_check_result, save_recurrence_suggest_result
    )
    logger.debug("plan_analyze_handler import 완료")

    from app.modules.claude_worker.services.plan_archive_insight_handler import (
        save_plan_archive_insight_result,
    )
    logger.debug("plan_archive_insight_handler import 완료")

    from app.core.database import is_connection_error
    logger.debug("is_connection_error import 완료")

    logger.info("모든 모듈 import 완료")

except Exception as e:
    import traceback
    logger.critical(f"모듈 import 중 치명적 오류: {e}")
    logger.critical(f"Traceback:\n{traceback.format_exc()}")
    AsyncLoggerManager.shutdown()
    sys.exit(1)


def parse_date(date_str: Optional[str]) -> Optional[date]:
    """날짜 문자열을 date 객체로 변환."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


INSTAGRAM_ENTITY_TAGS = {"이벤트", "팝업", "홍보대사", "기타"}
INSTAGRAM_NON_ENTITY_TAGS = {"리그램", "후기"}
INSTAGRAM_MOJIBAKE_TEXT_KEYS = ("tag", "summary", "purchase_required", "organizer")
INSTAGRAM_MOJIBAKE_LOCATION_KEYS = ("venue_name", "address")


def _truncate_for_log(value, limit: int = 240) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _contains_hangul(text: str) -> bool:
    return any("\uac00" <= ch <= "\ud7a3" for ch in text)


def try_reverse_decode_text(text: Optional[str]) -> Optional[str]:
    """UTF-8/locale mojibake 후보를 역변환한다."""
    if not isinstance(text, str) or not text or "\ufffd" in text:
        return None

    for source_encoding in ("cp949", "latin1", "cp1252"):
        try:
            repaired = text.encode(source_encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if repaired == text or "\ufffd" in repaired or not _contains_hangul(repaired):
            continue
        return repaired
    return None


def repair_instagram_payload_mojibake(payload: Optional[dict]) -> tuple[Optional[dict], bool]:
    """Instagram payload의 주요 한글 필드를 역변환 가능한 경우 복구한다."""
    if not isinstance(payload, dict):
        return payload, False

    repaired = dict(payload)
    changed = False

    for key in INSTAGRAM_MOJIBAKE_TEXT_KEYS:
        value = repaired.get(key)
        fixed = try_reverse_decode_text(value)
        if fixed is not None:
            repaired[key] = fixed
            changed = True

    prizes = repaired.get("prizes")
    if isinstance(prizes, list):
        new_prizes = []
        for item in prizes:
            fixed = try_reverse_decode_text(item) if isinstance(item, str) else None
            new_prizes.append(fixed if fixed is not None else item)
            changed = changed or fixed is not None
        repaired["prizes"] = new_prizes

    location = repaired.get("location")
    if isinstance(location, dict):
        new_location = dict(location)
        for key in INSTAGRAM_MOJIBAKE_LOCATION_KEYS:
            fixed = try_reverse_decode_text(new_location.get(key))
            if fixed is not None:
                new_location[key] = fixed
                changed = True
        repaired["location"] = new_location

    return repaired, changed


def _iter_instagram_payload_texts(payload: Optional[dict]):
    if not isinstance(payload, dict):
        return

    for key in INSTAGRAM_MOJIBAKE_TEXT_KEYS:
        value = payload.get(key)
        if isinstance(value, str):
            yield value

    prizes = payload.get("prizes")
    if isinstance(prizes, list):
        for item in prizes:
            if isinstance(item, str):
                yield item

    location = payload.get("location")
    if isinstance(location, dict):
        for key in INSTAGRAM_MOJIBAKE_LOCATION_KEYS:
            value = location.get(key)
            if isinstance(value, str):
                yield value


def instagram_payload_has_mojibake(
    payload: Optional[dict],
    raw_response: Optional[str] = None,
) -> bool:
    """Instagram payload/raw_response가 mojibake 징후를 가지는지 판별한다."""
    if isinstance(raw_response, str) and "\ufffd" in raw_response:
        return True

    for text in _iter_instagram_payload_texts(payload):
        if "\ufffd" in text:
            return True
        if try_reverse_decode_text(text) is not None:
            return True

    return False


def extract_instagram_payload(result_value, raw_response: Optional[str] = None) -> Optional[dict]:
    """저장된 result/raw_response에서 Instagram inner payload를 복구한다."""
    for candidate in (result_value, raw_response):
        if candidate in (None, ""):
            continue
        try:
            payload = normalize_json_payload(candidate)
        except ValueError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def save_instagram_result(db, post_id: int, llm_result: dict) -> bool:
    """Instagram 게시물에 LLM 분류 결과 저장 및 분류 테이블에 레코드 생성.

    Args:
        db: DB 세션
        post_id: Instagram 게시물 ID
        llm_result: LLM 분류 결과 dict

    Returns:
        성공 여부
    """
    from app.models import InstagramPost
    from app.models.event import Event
    from app.models.popup import Popup
    from app.models.uncategorized_post import UncategorizedPost

    try:
        post = db.query(InstagramPost).filter(InstagramPost.id == post_id).first()
        if not post:
            logger.error(f"Instagram post not found: {post_id}")
            return False

        if not isinstance(llm_result, dict):
            logger.error(
                f"Instagram result payload must be dict: post_id={post_id}, "
                f"type={type(llm_result).__name__}, payload={_truncate_for_log(llm_result)}"
            )
            return False

        # 이벤트 기간 파싱
        event_period = llm_result.get("event_period")
        event_start = None
        event_end = None
        if event_period is not None:
            if not isinstance(event_period, dict):
                logger.error(
                    f"Instagram result event_period shape invalid: post_id={post_id}, "
                    f"type={type(event_period).__name__}, payload={_truncate_for_log(event_period)}"
                )
                return False
            event_start = parse_date(event_period.get("start"))
            event_end = parse_date(event_period.get("end"))

        # 발표일 파싱
        announcement_date = parse_date(llm_result.get("announcement_date"))

        # 분류 태그에 따라 적절한 테이블에 레코드 생성
        tag = llm_result.get("tag")
        if tag not in INSTAGRAM_ENTITY_TAGS and tag not in INSTAGRAM_NON_ENTITY_TAGS:
            logger.error(
                f"Instagram result tag invalid: post_id={post_id}, tag={tag!r}, "
                f"keys={sorted(llm_result.keys())}"
            )
            return False

        llm_urls = llm_result.get("urls")
        if llm_urls is None:
            llm_urls = []
        elif not isinstance(llm_urls, list):
            logger.error(
                f"Instagram result urls shape invalid: post_id={post_id}, "
                f"type={type(llm_urls).__name__}, payload={_truncate_for_log(llm_urls)}"
            )
            return False

        location = llm_result.get("location")
        if location is None:
            location = {}
        elif not isinstance(location, dict):
            logger.error(
                f"Instagram result location shape invalid: post_id={post_id}, "
                f"type={type(location).__name__}, payload={_truncate_for_log(location)}"
            )
            return False

        # 썸네일 URL 추출
        thumbnail_url = None
        if post.images:
            images = post.images or []
            if images:
                thumbnail_url = images[0].get("src") if isinstance(images[0], dict) else images[0]

        if tag == "이벤트":
            # Event 테이블에 생성
            event = Event(
                title=llm_result.get("summary") or f"{post.account}의 이벤트",
                thumbnail_url=thumbnail_url,
                event_type="event",
                event_url=llm_urls[0] if llm_urls else None,
                additional_urls=llm_urls[1:] if len(llm_urls) > 1 else [],
                event_start=event_start,
                event_end=event_end,
                announcement_date=announcement_date,
                organizer=llm_result.get("organizer"),
                summary=llm_result.get("summary"),
                prizes=llm_result.get("prizes") or [],
                winner_count=llm_result.get("winner_count"),
                purchase_required=llm_result.get("purchase_required"),
                source_type="instagram",
                source_instagram_post_id=post.id,
                source_instagram_url=post.url,
                source_instagram_account=post.account,
            )
            db.add(event)
            db.flush()  # ID 생성
            post.classified_type = "event"
            post.classified_id = event.id
            post.classified_at = datetime.now()
            logger.info(f"Created Event {event.id} from Instagram post {post_id}")

        elif tag == "팝업":
            # Popup 테이블에 생성
            popup = Popup(
                title=llm_result.get("summary") or f"{post.account}의 팝업",
                thumbnail_url=thumbnail_url,
                venue_name=location.get("venue_name"),
                address=location.get("address"),
                start_date=event_start,
                end_date=event_end,
                organizer=llm_result.get("organizer"),
                summary=llm_result.get("summary"),
                official_url=llm_urls[0] if llm_urls else None,
                additional_urls=llm_urls[1:] if len(llm_urls) > 1 else [],
                source_type="instagram",
                source_instagram_post_id=post.id,
                source_instagram_url=post.url,
                source_instagram_account=post.account,
            )
            db.add(popup)
            db.flush()  # ID 생성
            post.classified_type = "popup"
            post.classified_id = popup.id
            post.classified_at = datetime.now()
            logger.info(f"Created Popup {popup.id} from Instagram post {post_id}")

        elif tag in ("홍보대사", "기타"):
            # UncategorizedPost 테이블에 생성
            uncategorized = UncategorizedPost(
                original_tag=tag,
                title=llm_result.get("summary") or f"{post.account}의 게시물",
                summary=llm_result.get("summary"),
                organizer=llm_result.get("organizer"),
                event_start=event_start,
                event_end=event_end,
                announcement_date=announcement_date,
                prizes=llm_result.get("prizes") or [],
                winner_count=llm_result.get("winner_count"),
                purchase_required=llm_result.get("purchase_required"),
                urls=llm_urls,
                source_instagram_post_id=post.id,
                source_instagram_url=post.url,
                source_instagram_account=post.account,
            )
            db.add(uncategorized)
            db.flush()  # ID 생성
            post.classified_type = "uncategorized"
            post.classified_id = uncategorized.id
            post.classified_at = datetime.now()
            logger.info(f"Created UncategorizedPost {uncategorized.id} from Instagram post {post_id}")

        elif tag in INSTAGRAM_NON_ENTITY_TAGS:
            post.classified_type = None
            post.classified_id = None
            post.classified_at = datetime.now()
            logger.info(f"Instagram post {post_id} classified without entity: tag={tag}")

        logger.info(f"Instagram post {post_id} LLM result saved: tag={tag}")
        return True

    except Exception as e:
        if is_connection_error(e):
            logger.warning("PG connection error: %s", e)
        else:
            logger.error(f"Failed to save Instagram result: {e}", exc_info=True)
        db.rollback()
        return False


def mark_instagram_failed(db, post_id: int, error_message: str) -> bool:
    """Instagram 게시물 LLM 분류 실패 표시.

    Note: llm_* 필드가 제거되어 InstagramPost 직접 업데이트는 하지 않음.
    LLM 요청 상태는 llm_requests 테이블에서 관리됨.
    """
    logger.warning(f"Instagram post {post_id} LLM classification failed: {error_message}")
    return True


def save_universal_crawl_result(db, page_id: int, llm_result: dict) -> bool:
    """Universal Crawl 페이지에 LLM 분석 결과 저장 및 Event/Popup 자동 생성.

    Args:
        db: DB 세션
        page_id: CrawledPage ID
        llm_result: LLM 분석 결과 dict

    Returns:
        성공 여부
    """
    from app.models.universal_crawl import CrawledPage
    from app.models.event import Event
    from app.models.popup import Popup
    from app.models.entity_source import EntitySource
    from app.services.duplicate_detection_service import duplicate_detection_service
    from app.schemas.entity_source import EntitySourceCreate
    from app.services.entity_source_service import entity_source_service
    import json

    try:
        page = db.query(CrawledPage).filter(CrawledPage.id == page_id).first()
        if not page:
            logger.warning(f"CrawledPage not found: {page_id}")
            return False

        # 분석 결과 저장
        is_event = llm_result.get("is_event", False)
        is_popup = llm_result.get("is_popup", False)
        confidence = llm_result.get("confidence", 0)

        page.is_event = is_event or is_popup
        page.analysis_result = json.dumps(llm_result, ensure_ascii=False)

        # 이벤트 자동 생성 (confidence >= 0.7)
        if is_event and confidence >= 0.7:
            event_data = _extract_event_data_from_llm(llm_result, page.url)
            duplicate_result = duplicate_detection_service.find_duplicate_event(db, event_data)

            if duplicate_result:
                # 기존 이벤트에 출처 추가
                existing_event, similarity = duplicate_result
                _add_source_to_event(db, existing_event, page, llm_result)
                page.event_id = existing_event.id
                logger.info(f"CrawledPage {page_id}: added source to Event {existing_event.id} (similarity={similarity:.2f})")
            else:
                # URL 중복 체크: event_url이 이미 존재하면 스킵
                event_url = event_data.get("event_url")
                if event_url:
                    from app.services.event_service import event_service
                    existing_by_url = event_service.check_duplicate_url(db, event_url)
                    if existing_by_url:
                        page.event_id = existing_by_url.id
                        logger.info(f"CrawledPage {page_id}: URL already exists (event_id={existing_by_url.id}), skipping creation")
                    else:
                        # 새 이벤트 생성
                        event = _create_event_from_crawl(db, page, llm_result, event_data)
                        _add_source_to_event(db, event, page, llm_result, is_primary=True)
                        page.event_id = event.id
                        logger.info(f"CrawledPage {page_id}: created Event {event.id}")
                else:
                    # URL 없이 새 이벤트 생성
                    event = _create_event_from_crawl(db, page, llm_result, event_data)
                    _add_source_to_event(db, event, page, llm_result, is_primary=True)
                    page.event_id = event.id
                    logger.info(f"CrawledPage {page_id}: created Event {event.id}")

        # 팝업 자동 생성 (confidence >= 0.7)
        elif is_popup and confidence >= 0.7:
            popup_data = _extract_popup_data_from_llm(llm_result, page.url)
            duplicate_result = duplicate_detection_service.find_duplicate_popup(db, popup_data)

            if duplicate_result:
                # 기존 팝업에 출처 추가
                existing_popup, similarity = duplicate_result
                _add_source_to_popup(db, existing_popup, page, llm_result)
                page.popup_id = existing_popup.id
                logger.info(f"CrawledPage {page_id}: added source to Popup {existing_popup.id} (similarity={similarity:.2f})")
            else:
                # 새 팝업 생성
                popup = _create_popup_from_crawl(db, page, llm_result, popup_data)
                _add_source_to_popup(db, popup, page, llm_result, is_primary=True)
                page.popup_id = popup.id
                logger.info(f"CrawledPage {page_id}: created Popup {popup.id}")

        logger.info(f"CrawledPage {page_id} LLM result saved: is_event={is_event}, is_popup={is_popup}")
        return True

    except Exception as e:
        if is_connection_error(e):
            logger.warning("PG connection error: %s", e)
        else:
            logger.error(f"Failed to save universal crawl result: {e}", exc_info=True)
        db.rollback()
        return False


def _extract_event_data_from_llm(llm_result: dict, source_url: str) -> dict:
    """LLM 결과에서 이벤트 데이터 추출."""
    event_period = llm_result.get("event_period") or {}
    return {
        "title": llm_result.get("title") or llm_result.get("summary"),
        "event_url": llm_result.get("event_url") or llm_result.get("participation_url"),
        "event_start": parse_date(event_period.get("start")),
        "event_end": parse_date(event_period.get("end")),
        "organizer": llm_result.get("organizer"),
        "prizes": llm_result.get("prizes") or [],
        "source_url": source_url,
    }


def _extract_popup_data_from_llm(llm_result: dict, source_url: str) -> dict:
    """LLM 결과에서 팝업 데이터 추출."""
    event_period = llm_result.get("event_period") or {}
    location = llm_result.get("location") or {}
    return {
        "title": llm_result.get("title") or llm_result.get("summary"),
        "brand": llm_result.get("brand") or llm_result.get("organizer"),
        "venue_name": location.get("venue_name"),
        "address": location.get("address"),
        "start_date": parse_date(event_period.get("start")),
        "end_date": parse_date(event_period.get("end")),
        "source_url": source_url,
    }


def _create_event_from_crawl(db, page, llm_result: dict, event_data: dict):
    """CrawledPage에서 Event 생성."""
    from app.models.event import Event
    import json

    urls = llm_result.get("urls") or []

    event = Event(
        title=event_data.get("title") or "제목 없음",
        event_type="event",
        event_url=event_data.get("event_url") or (urls[0] if urls else None),
        additional_urls=urls[1:] if len(urls) > 1 else [],
        event_start=event_data.get("event_start"),
        event_end=event_data.get("event_end"),
        announcement_date=parse_date(llm_result.get("announcement_date")),
        organizer=event_data.get("organizer"),
        summary=llm_result.get("summary"),
        prizes=event_data.get("prizes") or [],
        winner_count=llm_result.get("winner_count"),
        purchase_required=llm_result.get("purchase_required"),
        source_type="web",
        source_url=page.url,
        input_source="ai",
        source_count=1,
        confidence_score=int((llm_result.get("confidence") or 0.5) * 100),
    )
    db.add(event)
    db.flush()
    return event


def _create_popup_from_crawl(db, page, llm_result: dict, popup_data: dict):
    """CrawledPage에서 Popup 생성."""
    from app.models.popup import Popup

    urls = llm_result.get("urls") or []

    popup = Popup(
        title=popup_data.get("title") or "제목 없음",
        brand=popup_data.get("brand"),
        venue_name=popup_data.get("venue_name"),
        address=popup_data.get("address"),
        start_date=popup_data.get("start_date"),
        end_date=popup_data.get("end_date"),
        organizer=llm_result.get("organizer"),
        summary=llm_result.get("summary"),
        official_url=urls[0] if urls else None,
        additional_urls=urls[1:] if len(urls) > 1 else [],
        source_type="web",
        source_url=page.url,
        input_source="ai",
        source_count=1,
        confidence_score=int((llm_result.get("confidence") or 0.5) * 100),
    )
    db.add(popup)
    db.flush()
    return popup


def _add_source_to_event(db, event, page, llm_result: dict, is_primary: bool = False):
    """Event에 출처 추가."""
    from app.models.entity_source import EntitySource
    import json

    source = EntitySource(
        entity_type="event",
        entity_id=event.id,
        source_type="web",
        source_id=page.id,
        source_url=page.url,
        priority=60,  # web source default priority
        is_primary=1 if is_primary else 0,
        extracted_data=json.dumps(llm_result, ensure_ascii=False),
    )
    db.add(source)
    db.flush()

    # source_count 및 primary_source_id 업데이트
    if is_primary:
        event.primary_source_id = source.id
    event.source_count = (event.source_count or 0) + 1


def _add_source_to_popup(db, popup, page, llm_result: dict, is_primary: bool = False):
    """Popup에 출처 추가."""
    from app.models.entity_source import EntitySource
    import json

    source = EntitySource(
        entity_type="popup",
        entity_id=popup.id,
        source_type="web",
        source_id=page.id,
        source_url=page.url,
        priority=60,
        is_primary=1 if is_primary else 0,
        extracted_data=json.dumps(llm_result, ensure_ascii=False),
    )
    db.add(source)
    db.flush()

    if is_primary:
        popup.primary_source_id = source.id
    popup.source_count = (popup.source_count or 0) + 1


def mark_universal_crawl_failed(db, page_id: int, error_message: str) -> bool:
    """Universal Crawl 페이지 LLM 분석 실패 표시.

    Note: LLM 요청 상태는 llm_requests 테이블에서 관리됨.
    """
    logger.warning(f"CrawledPage {page_id} LLM analysis failed: {error_message}")
    return True


def save_writing_refine_result(db, request, result: dict) -> bool:
    """교정 결과를 GeneratedWriting.refined_content에 저장.

    Args:
        db: DB 세션
        request: LLMRequest 객체
        result: LLM 실행 결과

    Returns:
        성공 여부
    """
    from app.models.writing import GeneratedWriting

    try:
        writing_id = int(request.caller_id)
        writing = db.query(GeneratedWriting).filter(
            GeneratedWriting.id == writing_id
        ).first()

        if not writing:
            logger.warning(f"GeneratedWriting not found: {writing_id}")
            return False

        # 교정된 글 저장
        writing.refined_content = result.get("raw_response", "")
        writing.refined_at = datetime.now()
        db.commit()
        logger.info(f"교정 완료: writing_id={writing_id}")
        return True

    except Exception as e:
        if is_connection_error(e):
            logger.warning("PG connection error: %s", e)
        else:
            logger.error(f"Failed to save writing refine result: {e}", exc_info=True)
        db.rollback()
        return False


def save_writing_generate_result(db, request, result: dict) -> bool:
    """writing_generate 결과 → GeneratedWriting 저장.

    WritingWorker에서 생성한 요청의 결과를 저장합니다.

    Args:
        db: DB 세션
        request: LLMRequest 객체
        result: LLM 실행 결과

    Returns:
        성공 여부
    """
    from app.models.writing import GeneratedWriting, WritingSource
    from app.models.writing_element import WritingElement
    from app.modules.writing.services.element_selector import ElementSelector
    import json

    try:
        # writing_metadata 파싱
        metadata = {}
        if request.writing_metadata:
            metadata = json.loads(request.writing_metadata)

        task_type = metadata.get("task_type", "unknown")
        run_id = metadata.get("run_id")

        # JSON 결과에서 content 추출
        raw_response = result.get("raw_response", "")
        parsed_result = result.get("result", {})

        # Mix 타입: JSON에서 generated_writing 추출
        if task_type == "mix":
            content = parsed_result.get("generated_writing", "")
            if not content:
                # Fallback: raw_response에서 추출
                content = _extract_generated_content(raw_response)

            # 소스 ID 복원
            source_ids = metadata.get("source_ids", [])
            source_ids_str = ",".join(str(sid) for sid in source_ids)

            # 추출된 소재 저장
            analysis = parsed_result.get("analysis", [])
            extracted_topics = _save_extracted_topics(db, analysis)

            writing = GeneratedWriting(
                task_type=GeneratedWriting.TASK_TYPE_MIX,
                prompt_used=request.prompt[:2000] if len(request.prompt) > 2000 else request.prompt,
                source_ids=source_ids_str,
                content=content,
                raw_response=raw_response,
                extracted_topics=json.dumps(extracted_topics, ensure_ascii=False) if extracted_topics else None,
                schedule_run_id=run_id,
                llm_request_id=request.id,
            )
            db.add(writing)
            db.flush()

            # 소스 사용 이력 기록
            selector = ElementSelector(db)
            selector.record_source_usage(source_ids, writing.id)

            # 소재 추출 완료 마킹
            for sid in source_ids:
                source = db.query(WritingSource).filter(WritingSource.id == sid).first()
                if source:
                    source.topic_extracted_at = datetime.now()

        # Random/Keyword 타입
        else:
            content = _extract_generated_content(raw_response)

            # selected_elements JSON
            selected_elements = metadata.get("selected_elements", {})
            selected_json = json.dumps(selected_elements, ensure_ascii=False)

            writing = GeneratedWriting(
                task_type=task_type,
                prompt_used=request.prompt[:2000] if len(request.prompt) > 2000 else request.prompt,
                source_ids=None,
                content=content,
                raw_response=raw_response,
                selected_elements=selected_json,
                schedule_run_id=run_id,
                llm_request_id=request.id,
            )
            db.add(writing)
            db.flush()

            # 요소 사용 이력 기록
            selector = ElementSelector(db)
            element_ids = []
            for key, value in selected_elements.items():
                if key == "keywords":
                    # List of element names
                    continue
                elif isinstance(value, str):
                    # Single element name
                    elem = db.query(WritingElement).filter(WritingElement.name == value).first()
                    if elem:
                        element_ids.append(elem)

            if element_ids:
                selector.record_element_usage(element_ids, writing.id)

        db.commit()
        logger.info(f"writing_generate result saved: writing_id={writing.id}, task_type={task_type}")
        return True

    except Exception as e:
        if is_connection_error(e):
            logger.warning("PG connection error: %s", e)
        else:
            logger.error(f"Failed to save writing_generate result: {e}", exc_info=True)
        db.rollback()
        return False


def _extract_generated_content(raw_response: str) -> str:
    """LLM 응답에서 생성된 글 추출."""
    if not raw_response:
        return ""

    # --- 구분자가 있으면 이후 내용 추출
    if "---" in raw_response:
        parts = raw_response.split("---")
        for part in reversed(parts):
            stripped = part.strip()
            if stripped and len(stripped) > 100:
                return stripped

    return raw_response.strip()


def _save_extracted_topics(db, analysis: list) -> list[str]:
    """분석 결과에서 소재를 추출하여 writing_elements에 저장."""
    from app.models.writing_element import WritingElement

    saved_topics = []

    for item in analysis:
        topic = item.get("topic", "").strip()
        if not topic or len(topic) < 2:
            continue

        # 너무 짧거나 일반적인 단어 필터링
        if len(topic) <= 3 and topic in ["사랑", "마음", "추억", "가족", "행복"]:
            logger.debug(f"일반적인 단어 스킵: {topic}")
            continue

        try:
            # 중복 체크
            existing = (
                db.query(WritingElement)
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
                logger.debug(f"기존 소재 빈도 증가: {topic} -> {existing.frequency}")
            else:
                new_element = WritingElement(
                    category=WritingElement.CATEGORY_TOPIC,
                    name=topic,
                    source_type=WritingElement.SOURCE_TYPE_AUTO,
                    frequency=1,
                    is_active=True,
                )
                db.add(new_element)
                logger.info(f"새 소재 추가: {topic}")

            saved_topics.append(topic)

        except Exception as e:
            logger.warning(f"소재 저장 실패: {topic} - {e}")
            continue

    if saved_topics:
        db.commit()
        logger.info(f"소재 {len(saved_topics)}개 저장 완료: {saved_topics}")

    return saved_topics


def save_writing_result(db, request, result: dict) -> bool:
    """Writing LLM 결과 저장 (배치용).

    Args:
        db: DB 세션
        request: LLMRequest 객체
        result: LLM 실행 결과

    Returns:
        성공 여부
    """
    from app.modules.writing.models.writing_batch import WritingBatch
    from app.models.writing import GeneratedWriting
    import json

    try:
        # writing_metadata 파싱
        metadata = {}
        if request.writing_metadata:
            metadata = json.loads(request.writing_metadata)

        task_type = metadata.get("task_type", "unknown")

        # GeneratedWriting 생성
        content = result.get("raw_response", "")
        if not content and result.get("result"):
            # JSON 결과에서 content 추출 시도
            llm_result = result.get("result", {})
            if isinstance(llm_result, dict):
                content = llm_result.get("content", str(llm_result))
            else:
                content = str(llm_result)

        writing = GeneratedWriting(
            task_type=task_type,
            content=content[:10000] if content else "",
            schedule_run_id=None,  # 배치에서는 schedule_run_id 없음
            llm_request_id=request.id,
        )

        # 메타데이터 기반 추가 필드 설정
        if task_type == "mix":
            source_ids = metadata.get("source_ids", [])
            if source_ids:
                writing.source_ids = json.dumps(source_ids)
        elif task_type in ["random", "keyword"]:
            selected = metadata.get("selected_elements", {})
            writing.selected_elements = json.dumps(selected, ensure_ascii=False)

        db.add(writing)
        db.flush()  # writing.id 생성

        # 교정 요청 자동 생성
        refine_prompt_path = Path(__file__).parent.parent.parent / "modules" / "writing" / "prompts" / "refine_prompt.md"
        if refine_prompt_path.exists():
            refine_template = refine_prompt_path.read_text(encoding="utf-8")
            refine_prompt = refine_template.replace("{content}", writing.content)
            llm_service = LLMService(db)
            provider, model = llm_service.resolve_provider_model(
                caller_type="writing_refine",
                provider=None,
                model=None,
            )

            refine_request = LLMRequest(
                caller_type="writing_refine",
                caller_id=str(writing.id),
                prompt=refine_prompt,
                status="pending",
                requested_by="auto",
                request_source="writing_worker",
                provider=provider,
                model=model,
            )
            db.add(refine_request)
            logger.info(f"교정 요청 생성: writing_id={writing.id}")

        # 배치 카운트 업데이트
        if request.writing_batch_id:
            batch = db.query(WritingBatch).filter(
                WritingBatch.id == request.writing_batch_id
            ).first()
            if batch:
                batch.increment_completed()
                logger.info(f"배치 진행: batch_id={batch.id}, completed={batch.completed_count}/{batch.total_count}")

        db.commit()
        logger.info(f"Writing result saved: request_id={request.id}, task_type={task_type}")
        return True

    except Exception as e:
        if is_connection_error(e):
            logger.warning("PG connection error: %s", e)
        else:
            logger.error(f"Failed to save writing result: {e}", exc_info=True)
        db.rollback()
        return False


def mark_writing_failed(db, request, error_message: str) -> bool:
    """Writing LLM 실패 처리.

    Args:
        db: DB 세션
        request: LLMRequest 객체
        error_message: 에러 메시지

    Returns:
        성공 여부
    """
    from app.modules.writing.models.writing_batch import WritingBatch

    try:
        # 배치 카운트 업데이트
        if request.writing_batch_id:
            batch = db.query(WritingBatch).filter(
                WritingBatch.id == request.writing_batch_id
            ).first()
            if batch:
                batch.increment_failed()
                logger.warning(f"Writing 요청 실패: batch_id={batch.id}, request_id={request.id}, error={error_message}")

        db.commit()
        return True

    except Exception as e:
        if is_connection_error(e):
            logger.warning("PG connection error: %s", e)
        else:
            logger.error(f"Failed to mark writing failed: {e}", exc_info=True)
        db.rollback()
        return False


def save_event_import_result(db, request, result: dict) -> bool:
    """event_import 결과 → Event 생성.

    Args:
        db: DB 세션
        request: LLMRequest 객체
        result: LLM 실행 결과

    Returns:
        성공 여부
    """
    from app.models.event import Event
    import json

    try:
        parsed_event = result.get("result", {})

        if not parsed_event:
            logger.warning(f"event_import {request.caller_id}: LLM 결과 없음")
            return False

        # 비이벤트 처리
        if not parsed_event.get("is_event", True):
            logger.info(f"비이벤트: {request.caller_id}")
            return True

        # 날짜 파싱
        event_period = parsed_event.get("event_period") or {}
        event_start = parse_date(event_period.get("start"))
        event_end = parse_date(event_period.get("end"))
        announcement_date = parse_date(parsed_event.get("announcement_date"))

        # URL 리스트
        urls = parsed_event.get("urls") or []

        # Event 생성
        event = Event(
            title=parsed_event.get("title") or "제목 없음",
            event_type="event",
            event_url=urls[0] if urls else request.caller_id,  # caller_id는 원본 URL
            additional_urls=urls[1:] if len(urls) > 1 else [],
            event_start=event_start,
            event_end=event_end,
            announcement_date=announcement_date,
            organizer=parsed_event.get("organizer"),
            summary=parsed_event.get("summary"),
            prizes=parsed_event.get("prizes") or [],
            winner_count=parsed_event.get("winner_count"),
            purchase_required=parsed_event.get("purchase_required"),
            source_type="web",
            source_url=request.caller_id,
            input_source="ai",
        )
        db.add(event)
        db.flush()

        logger.info(f"Event 생성 완료: id={event.id}, title={event.title}")
        return True

    except Exception as e:
        if is_connection_error(e):
            logger.warning("PG connection error: %s", e)
        else:
            logger.error(f"Failed to save event_import result: {e}", exc_info=True)
        db.rollback()
        return False


def save_topic_extract_result(db, caller_id: str, llm_result: dict) -> bool:
    """소재 추출 LLM 결과를 writing_elements에 저장.

    Args:
        db: DB 세션
        caller_id: 배치 식별자 (예: "manual_batch_1_231050")
        llm_result: LLM 결과 {"topics": [{"source_id": 1, "topic": "소재"}, ...]}

    Returns:
        성공 여부
    """
    from app.models.writing_element import WritingElement

    try:
        topics = llm_result.get("topics", [])
        if not topics:
            logger.info(f"topic_extract {caller_id}: 추출된 소재 없음")
            return True

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
                    db.query(WritingElement)
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
                    db.add(new_element)

                saved_count += 1

            except Exception as e:
                logger.warning(f"소재 저장 실패: {topic} - {e}")
                continue

        if saved_count:
            db.commit()
            logger.info(f"topic_extract {caller_id}: 소재 {saved_count}개 저장 완료")

        return True

    except Exception as e:
        if is_connection_error(e):
            logger.warning("PG connection error: %s", e)
        else:
            logger.error(f"topic_extract 결과 저장 실패: {e}", exc_info=True)
        db.rollback()
        return False


def _extract_json_from_markdown(text: str) -> Optional[dict]:
    """마크다운 코드블록에서 JSON 추출.

    Args:
        text: 마크다운 텍스트

    Returns:
        파싱된 JSON dict 또는 None
    """
    import re
    import json

    # ```json 시작 위치 찾기
    json_start_match = re.search(r"```json\s*\n", text)
    if not json_start_match:
        return None

    start_pos = json_start_match.end()

    # 브레이스 카운팅으로 JSON 끝 찾기
    brace_count = 0
    in_string = False
    escape_next = False
    json_end_pos = -1

    for i in range(start_pos, len(text)):
        char = text[i]

        if escape_next:
            escape_next = False
            continue

        if char == '\\':
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if not in_string:
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    json_end_pos = i + 1
                    break

    if json_end_pos == -1:
        logger.debug("마크다운 블록 JSON 끝을 찾을 수 없음")
        return None

    json_str = text[start_pos:json_end_pos]

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.debug(f"마크다운 블록 JSON 파싱 실패: {e}")
        return None


def _extract_json_braces(text: str) -> Optional[dict]:
    """{ } 블록 추출 및 파싱.

    Args:
        text: 텍스트

    Returns:
        파싱된 JSON dict 또는 None
    """
    import re
    import json

    brace_match = re.search(r"\{[\s\S]*\}", text)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError as e:
            logger.debug(f"중괄호 블록 JSON 파싱 실패: {e}")
            return None
    return None


def _try_parse_json(text: str) -> Optional[dict]:
    """전체 텍스트를 JSON으로 파싱 시도.

    Args:
        text: 텍스트

    Returns:
        파싱된 JSON dict 또는 None
    """
    import json

    try:
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        logger.debug(f"전체 텍스트 JSON 파싱 실패: {e}")
        return None


def save_pytest_fix_result(db, request, result: dict) -> bool:
    """pytest 실패 테스트 수정계획 LLM 결과를 TestResult.fix_plan에 저장.

    Args:
        db: DB 세션
        request: LLMRequest 객체 (caller_id 형식: "{run_id}__{safe_test_name}")
        result: LLM 결과 {"result": ..., "raw_response": "..."}

    Returns:
        성공 여부 (실패 시 False, 예외 미전파)
    """
    from app.models.test_run import TestResult

    try:
        raw_response = result.get("raw_response") or result.get("result") or ""
        if isinstance(raw_response, dict):
            raw_response = str(raw_response)

        # caller_id 파싱: "{run_id}__{safe_test_name}"
        caller_id = request.caller_id
        if "__" not in caller_id:
            logger.warning(f"pytest_fix: 잘못된 caller_id 형식: {caller_id}")
            return False

        run_id_str, _ = caller_id.split("__", 1)
        try:
            run_id = int(run_id_str)
        except ValueError:
            logger.warning(f"pytest_fix: run_id 파싱 실패: {caller_id}")
            return False

        # llm_request_id로 TestResult 조회
        test_result = (
            db.query(TestResult)
            .filter(
                TestResult.llm_request_id == request.id,
                TestResult.test_run_id == run_id,
            )
            .first()
        )

        if not test_result:
            logger.warning(f"pytest_fix: TestResult 미존재 (llm_request_id={request.id}, run_id={run_id})")
            return False

        test_result.fix_plan = raw_response
        db.commit()
        logger.info(f"pytest_fix: fix_plan 저장 완료 (test_result_id={test_result.id})")
        return True

    except Exception as e:
        if is_connection_error(e):
            logger.warning("PG connection error: %s", e)
        else:
            logger.error(f"pytest_fix: save_pytest_fix_result 오류: {e}", exc_info=True)
        return False


def save_report_result(db, request, result: dict) -> bool:
    """보고서 생성 LLM 결과를 generated_reports에 저장.

    Args:
        db: DB 세션
        request: LLMRequest 객체
        result: LLM 결과 {"result": {...}, "raw_response": "..."}

    Returns:
        성공 여부
    """
    from app.modules.reports.models.generated_report import GeneratedReport
    import json

    try:
        llm_result = result.get("result", {})
        raw_response = result.get("raw_response", "")

        # JSON 파싱 실패 시 raw_response에서 JSON 재추출 시도
        if not llm_result and raw_response:
            logger.info(f"report {request.caller_id}: JSON 파싱 실패, 재추출 시도")

            # 방법 1: ```json ... ``` 블록에서 추출
            llm_result = _extract_json_from_markdown(raw_response)
            if llm_result:
                logger.info(f"report {request.caller_id}: 마크다운 블록에서 JSON 추출 성공")

            # 방법 2: { } 블록 추출
            if not llm_result:
                llm_result = _extract_json_braces(raw_response)
                if llm_result:
                    logger.info(f"report {request.caller_id}: 중괄호 블록에서 JSON 추출 성공")

            # 방법 3: 전체를 JSON으로 파싱 시도
            if not llm_result:
                llm_result = _try_parse_json(raw_response)
                if llm_result:
                    logger.info(f"report {request.caller_id}: 전체 텍스트 JSON 파싱 성공")

        # 최종 fallback: raw_response를 content로
        if not llm_result:
            if raw_response:
                logger.warning(f"report {request.caller_id}: 모든 JSON 추출 실패, raw_response를 content로 사용")
            content = raw_response
            title = None
            summary = None
            statistics = {}
        else:
            content = llm_result.get("content", "")
            title = llm_result.get("title")
            summary = llm_result.get("summary")
            statistics = llm_result.get("statistics", {})

        # caller_id에서 report_type, date 파싱
        # 형식: "report_type_YYYYMMDD"
        parts = request.caller_id.split("_")
        if len(parts) < 2:
            logger.error(f"Invalid caller_id format: {request.caller_id}")
            return False

        date_str = parts[-1]  # YYYYMMDD
        report_type = "_".join(parts[:-1])  # 나머지는 report_type

        try:
            period_end = datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            logger.error(f"Invalid date in caller_id: {date_str}")
            return False

        # period_start는 period_end - 1일 (daily 기준)
        from datetime import timedelta
        period_start = period_end - timedelta(days=1)

        report = GeneratedReport(
            report_type=report_type,
            period_start=period_start,
            period_end=period_end,
            title=title or f"{report_type} report",
            content=content,
            summary=summary,
            statistics=json.dumps(statistics, ensure_ascii=False),
            llm_request_id=request.id,
            schedule_run_id=None,  # TODO: schedule_run_id 연결
            format="markdown"
        )
        db.add(report)
        db.commit()

        logger.info(f"report {request.caller_id}: 보고서 저장 완료 (id={report.id})")
        return True

    except Exception as e:
        if is_connection_error(e):
            logger.warning("PG connection error: %s", e)
        else:
            logger.error(f"report 결과 저장 실패: {e}", exc_info=True)
        db.rollback()
        return False


class LLMWorker:
    """Claude LLM 워커."""

    def __init__(self):
        self.shutdown_event = asyncio.Event()
        self.continue_event = asyncio.Event()  # 작업 완료 시 즉시 깨우기용
        self.check_interval = 10  # 10초마다 체크
        self.pid = os.getpid()
        self.start_time: datetime = None
        self.worker_id: str = None
        self._last_heartbeat_time: float = 0

    async def start(self):
        """워커 시작."""
        logger.info(f"LLM 워커 시작 (PID: {self.pid})")
        self.start_time = datetime.now()

        # 워커 상태 등록
        self._register_worker_status()

        # Stale 요청 정리 (이전 워커가 비정상 종료된 경우)
        self._cleanup_stale_requests()

        try:
            await self._main_loop()
        finally:
            await self._cleanup()

    def _register_worker_status(self):
        """워커 상태를 DB에 등록."""
        db = SessionLocal()
        try:
            service = LLMService(db)
            self.worker_id = str(uuid.uuid4())
            service.register_worker(self.worker_id, self.pid)
            logger.info(f"워커 상태 등록 완료: worker_id={self.worker_id}")
        except Exception as e:
            logger.error(f"워커 상태 등록 실패: {e}")
        finally:
            db.close()

    def _cleanup_stale_requests(self):
        """Stale 요청 정리 (워커 시작 시 호출)."""
        db = SessionLocal()
        try:
            service = LLMService(db)
            result = service.run_cleanup()
            if result["stale_processing"] > 0 or result["old_history"] > 0:
                logger.info(
                    f"Cleanup 완료: stale_processing={result['stale_processing']}, "
                    f"old_history={result['old_history']}"
                )
        except Exception as e:
            logger.error(f"Cleanup 실패: {e}")
        finally:
            db.close()

    def _update_heartbeat(self):
        """하트비트를 Redis에 publish한다."""
        from app.shared.worker.health_redis import WorkerHealthRedis
        WorkerHealthRedis.publish("claude", self.pid, "running")

    def _update_worker_state(self, state: str, request_id: int = None):
        """워커 상태 업데이트."""
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = LLMService(db)
            service.update_worker_state(self.worker_id, state, request_id)
        except Exception as e:
            logger.warning(f"워커 상태 업데이트 실패: {e}")
        finally:
            db.close()

    def _increment_processed(self):
        """처리 카운트 증가."""
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = LLMService(db)
            service.increment_processed(self.worker_id)
        except Exception as e:
            logger.warning(f"처리 카운트 증가 실패: {e}")
        finally:
            db.close()

    def _increment_error(self):
        """에러 카운트 증가."""
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = LLMService(db)
            service.increment_error(self.worker_id)
        except Exception as e:
            logger.warning(f"에러 카운트 증가 실패: {e}")
        finally:
            db.close()

    def _mark_worker_dead(self):
        """워커를 종료 상태로 표시."""
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = LLMService(db)
            service.mark_worker_dead(self.worker_id)
            logger.info(f"워커 종료 상태 표시 완료: worker_id={self.worker_id}")
        except Exception as e:
            logger.error(f"워커 종료 상태 표시 실패: {e}")
        finally:
            db.close()

    async def stop(self):
        """워커 종료."""
        logger.info("LLM 워커 종료 요청")
        self.shutdown_event.set()

    async def _cleanup(self):
        """정리."""
        logger.info("LLM 워커 정리 시작")
        self._mark_worker_dead()
        logger.info("LLM 워커 정리 완료")
        AsyncLoggerManager.shutdown()

    async def _main_loop(self):
        """메인 루프."""
        logger.info(f"메인 루프 시작 (체크 간격: {self.check_interval}초)")

        while not self.shutdown_event.is_set():
            try:
                # Heartbeat 업데이트 (15초마다 1회)
                _now = time.monotonic()
                if _now - self._last_heartbeat_time >= 15:
                    self._update_heartbeat()
                    self._last_heartbeat_time = _now

                # Quota pause 자동 해제 체크
                await self._check_quota_resume()

                # Pending 요청 처리
                await self._process_pending_requests()

                # 대기 (continue_event 또는 shutdown_event 발생 시 즉시 깨어남)
                self.continue_event.clear()
                shutdown_task = asyncio.create_task(self.shutdown_event.wait())
                continue_task = asyncio.create_task(self.continue_event.wait())
                try:
                    done, pending = await asyncio.wait(
                        [shutdown_task, continue_task],
                        timeout=self.check_interval,
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                    if continue_task in done:
                        logger.debug("continue_event로 즉시 깨어남 - 다음 요청 처리")
                except asyncio.TimeoutError:
                    pass

            except asyncio.CancelledError:
                logger.info("메인 루프 취소됨")
                break
            except Exception as e:
                logger.error(f"메인 루프 오류: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _check_quota_resume(self):
        """만료된 quota pause 자동 해제 및 failed → pending 전환."""
        db = SessionLocal()
        try:
            service = LLMService(db)
            for provider in provider_registry.get_quota_providers():
                paused_until = service.get_provider_quota_pause(provider)
                if paused_until is None:
                    # None이지만 DB에 pause 레코드가 있을 수 있으므로 (만료된 경우) clear 시도
                    from app.modules.claude_worker.models.llm_request import LLMWorkerStatus
                    from datetime import datetime as _dt
                    stale = (
                        db.query(LLMWorkerStatus)
                        .filter(
                            LLMWorkerStatus.quota_paused_provider == provider,
                            LLMWorkerStatus.quota_paused_until <= _dt.now(),
                        )
                        .first()
                    )
                    if stale:
                        cleared = service.clear_provider_quota_pause(provider)
                        if cleared:
                            count = service.reset_quota_failed_requests(provider)
                            logger.info(f"[QUOTA] {provider} 쿼터 재개. {count}건 요청 pending 전환")
        except Exception as e:
            if is_connection_error(e):
                logger.warning("PG connection error: %s", e)
            else:
                logger.error(f"quota resume 체크 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _process_pending_requests(self):
        """Pending 요청 처리 (우선순위 큐 기반)."""
        db = SessionLocal()
        try:
            service = LLMService(db)

            window_decision = LLMExecutionWindowService().decide()
            if not window_decision.allowed:
                quota_pauses = [
                    service.get_provider_quota_pause(provider)
                    for provider in provider_registry.get_quota_providers()
                ]
                resume_at = max_resume_at(window_decision.next_allowed_at, *quota_pauses)
                blocked = service.get_pending_count()
                if blocked > 0:
                    logger.info(
                        "[WINDOW] LLM 요청 %s건 보류 중 (다음 재개 후보: %s)",
                        blocked,
                        resume_at,
                    )
                self._update_worker_state("paused_by_window", None)
                return

            # pause 중인 provider 조회
            exclude_providers = []
            for provider in provider_registry.get_quota_providers():
                paused_until = service.get_provider_quota_pause(provider)
                if paused_until:
                    exclude_providers.append(provider)
                    blocked = service.get_blocked_pending_count(provider)
                    if blocked > 0:
                        logger.info(f"[QUOTA] {provider} 요청 {blocked}건 차단 중 (재개: {paused_until})")

            request = service.get_next_request(exclude_providers=exclude_providers)

            if request:
                self._update_worker_state("idle", None)
                logger.info(
                    f"Pending 요청 발견: id={request.id}, queue={request.queue_name}, "
                    f"caller={request.caller_type}:{request.caller_id}, mode={getattr(request, 'mode', 'single')}"
                )
                if getattr(request, "mode", "single") == "chat":
                    await self._delegate_to_chat_executor(request, service)
                else:
                    await self._execute_request(request, db, service)
            elif exclude_providers:
                self._update_worker_state("paused_by_quota", None)
            else:
                self._update_worker_state("idle", None)

        except Exception as e:
            if is_connection_error(e):
                logger.warning("PG connection error: %s", e)
            else:
                logger.error(f"Pending 요청 처리 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _delegate_to_chat_executor(self, request: LLMRequest, service: LLMService):
        """Chat 요청을 Chat Executor에 위임 (Redis LPUSH)."""
        from app.shared.redis.client import RedisClient

        request_id = int(request.id)
        try:
            service.mark_processing(request_id)
            self._update_worker_state("processing", request_id)

            chat_session_id = f"llm-chat:stream:{request_id}"
            service.update_chat_session(request_id, chat_session_id)

            command = {
                "action": "execute",
                "request_id": request_id,
                "prompt": request.prompt,
                "provider": request.provider,
                "model": request.model,
                "cli_options": json.loads(request.cli_options) if request.cli_options else {},
                "chat_session_id": chat_session_id,
                "timestamp": datetime.now().isoformat(),
            }

            redis_client = await RedisClient.get_client()
            if redis_client:
                await redis_client.lpush("llm-chat:commands", json.dumps(command, ensure_ascii=False))
                logger.info(f"Chat 요청 위임: id={request_id} → llm-chat:commands")
            else:
                logger.error(f"Redis 연결 없음. chat 요청 위임 실패: id={request_id}")
                self._mark_request_failed_safely(
                    service,
                    service.db,
                    request_id,
                    "Redis 연결 없음 — chat 위임 실패",
                )
        except Exception as e:
            self._mark_request_failed_safely(service, service.db, request_id, str(e))
            logger.error("Chat 요청 위임 예외: id=%s error=%s", request_id, e, exc_info=True)
        finally:
            self._update_worker_state("idle", None)

    def _mark_request_failed_safely(
        self,
        service: LLMService,
        db,
        request_id: int,
        error_message: str,
        raw_response: str = "",
    ) -> None:
        """Rollback-required 세션에서도 요청을 failed로 마감한다."""
        message = str(error_message)

        if db is not None:
            try:
                db.rollback()
            except Exception as rollback_error:
                logger.warning(
                    "LLM 실패 finalizer rollback 실패: request_id=%s error=%s",
                    request_id,
                    rollback_error,
                )

        try:
            service.mark_failed(request_id, message, raw_response)
            return
        except Exception as mark_error:
            logger.error(
                "LLM 실패 상태 전이 실패: request_id=%s error=%s",
                request_id,
                mark_error,
                exc_info=True,
            )
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    pass

        fail_db = None
        try:
            fail_db = SessionLocal()
            LLMService(fail_db).mark_failed(request_id, message, raw_response)
        except Exception as fallback_error:
            logger.critical(
                "LLM 실패 상태 전이 최종 fallback 실패: request_id=%s error=%s",
                request_id,
                fallback_error,
                exc_info=True,
            )
        finally:
            if fail_db is not None:
                fail_db.close()

    async def _execute_request(
        self,
        request: LLMRequest,
        db,
        service: LLMService,
    ):
        """LLM 요청 실행."""
        request_id = int(request.id)
        caller_type = request.caller_type
        caller_id = request.caller_id
        queue_name = request.queue_name
        claim_service = None
        claim_acquired = False
        selected_profile = None
        stop_reason = "failed"
        error_summary = None
        try:
            # 처리 중으로 변경
            service.mark_processing(request_id)
            self._update_worker_state("processing", request_id)

            # caller_id 사전 검증 (Phase 2)
            if caller_type in ["instagram", "universal_crawl"]:
                try:
                    caller_id_int = int(caller_id)
                    if caller_type == "instagram":
                        from app.models import InstagramPost
                        post = db.query(InstagramPost).filter(InstagramPost.id == caller_id_int).first()
                        if not post:
                            logger.warning(f"사전 검증 실패: Instagram post {caller_id_int} 없음 (id={request_id})")
                            self._mark_request_failed_safely(service, db, request_id, f"Instagram post not found: {caller_id_int}")
                            self._update_worker_state("idle", None)
                            return
                        if not post.caption:
                            logger.warning(f"사전 검증 실패: Instagram post {caller_id_int} 캡션 없음 (id={request_id})")
                            self._mark_request_failed_safely(service, db, request_id, f"Instagram post has no caption: {caller_id_int}")
                            self._update_worker_state("idle", None)
                            return
                    elif caller_type == "universal_crawl":
                        from app.models.universal_crawl import CrawledPage
                        page = db.query(CrawledPage).filter(CrawledPage.id == caller_id_int).first()
                        if not page:
                            logger.warning(f"사전 검증 실패: CrawledPage {caller_id_int} 없음 (id={request_id})")
                            self._mark_request_failed_safely(service, db, request_id, f"CrawledPage not found: {caller_id_int}")
                            self._update_worker_state("idle", None)
                            return
                except ValueError:
                    logger.warning(f"사전 검증 실패: 유효하지 않은 caller_id '{caller_id}' (id={request_id})")
                    self._mark_request_failed_safely(service, db, request_id, f"Invalid caller_id (non-numeric): {caller_id}")
                    self._update_worker_state("idle", None)
                    return

            logger.info(f"LLM 실행 시작: id={request_id}, queue={queue_name}, caller_type={caller_type}")

            # cli_options 파싱 (JSON 문자열 → dict)
            cli_options = None
            if getattr(request, "cli_options", None):
                try:
                    cli_options = json.loads(request.cli_options)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"cli_options 파싱 실패: id={request_id}")

            # caller_type에 따라 도구 활성화 결정
            # - instagram, universal_crawl: Read 도구로 이미지 분석 가능
            # - image_classify: cli_options에서 allowed_tools 지정
            # - writing 관련: 도구 사용 금지 (도구 사용 시 글 작성 대신 프롬프트 분석만 함)
            enable_tools = caller_type in ["instagram", "universal_crawl"]

            # provider/model 해석 (요청값 > caller 기본값 > global 기본값 > 최종 claude/"")
            provider, model = service.resolve_provider_model(
                caller_type=caller_type,
                provider=getattr(request, "provider", None),
                model=getattr(request, "model", None),
            )

            if provider in provider_registry.get_quota_providers():
                from app.modules.claude_worker.services.profile_claim_service import ProfileClaimService
                from app.modules.claude_worker.services.profile_router import LLMProfileRouter

                router = LLMProfileRouter(db)
                route_providers = [provider]
                if caller_type == "plan_archive_analyze" and isinstance(cli_options, dict):
                    raw_candidates = cli_options.get("candidate_profiles")
                    if isinstance(raw_candidates, list):
                        candidate_engines = [
                            str(item.get("engine") or "").strip()
                            for item in raw_candidates
                            if isinstance(item, dict)
                        ]
                        route_providers = [
                            engine
                            for engine in dict.fromkeys(candidate_engines)
                            if engine in provider_registry.get_quota_providers()
                        ] or route_providers

                decision = None
                for route_provider in route_providers:
                    candidate_decision = router.select_profile(route_provider, model, request)
                    if candidate_decision.profile is not None:
                        provider = route_provider
                        decision = candidate_decision
                        break
                    decision = candidate_decision
                if decision.profile is None:
                    logger.info(
                        "[PROFILE-ROUTER] request %s pending 유지: provider=%s reason=%s next=%s blocked=%s",
                        request_id,
                        provider,
                        decision.reason,
                        decision.next_available_at,
                        decision.blocked_counts,
                    )
                    service.reset_to_pending(request_id, decision.reason)
                    if caller_type == "plan_archive_analyze":
                        try:
                            from app.modules.dev_runner.services.plan_archive_execution_service import (
                                PlanArchiveExecutionService,
                            )

                            PlanArchiveExecutionService(db).mark_request_blocked(
                                request_id,
                                decision.reason,
                                next_available_at=decision.next_available_at,
                            )
                        except Exception as exc:
                            logger.warning("[PLAN-ARCHIVE-EXEC] blocked sync 실패: request=%s error=%s", request_id, exc)
                    self._update_worker_state(
                        "paused_by_quota" if "quota" in decision.reason else "idle",
                        None,
                    )
                    return

                selected_profile = decision.profile
                claim_service = ProfileClaimService(db)
                claim = claim_service.claim(
                    request_id,
                    provider,
                    selected_profile.name,
                    capacity=selected_profile.capacity,
                )
                if claim is None:
                    logger.warning(
                        "[PROFILE-CLAIM] request %s claim 충돌: provider=%s profile=%s",
                        request_id,
                        provider,
                        selected_profile.name,
                    )
                    service.reset_to_pending(request_id, "profile_claim_conflict")
                    if caller_type == "plan_archive_analyze":
                        try:
                            from app.modules.dev_runner.services.plan_archive_execution_service import (
                                PlanArchiveExecutionService,
                            )

                            PlanArchiveExecutionService(db).mark_request_blocked(
                                request_id,
                                "profile_claim_conflict",
                            )
                        except Exception as exc:
                            logger.warning("[PLAN-ARCHIVE-EXEC] claim conflict sync 실패: request=%s error=%s", request_id, exc)
                    self._update_worker_state("idle", None)
                    return
                claim_acquired = True
                if caller_type == "plan_archive_analyze":
                    try:
                        from app.modules.dev_runner.services.plan_archive_execution_service import (
                            PlanArchiveExecutionService,
                        )

                        PlanArchiveExecutionService(db).mark_request_profile(
                            request_id,
                            provider,
                            selected_profile.name,
                        )
                    except Exception as exc:
                        logger.warning("[PLAN-ARCHIVE-EXEC] profile sync 실패: request=%s error=%s", request_id, exc)
                logger.info(
                    "[PROFILE-ROUTER] request %s → %s/%s",
                    request_id,
                    provider,
                    selected_profile.name,
                )

            # LLM 실행 (비동기 실행을 위해 run_in_executor 사용)
            loop = asyncio.get_event_loop()
            # cli_options에서 parse_json 옵션 읽기 (기본값: True)
            parse_json = True
            if cli_options and "parse_json" in cli_options:
                parse_json = bool(cli_options["parse_json"])

            result = await loop.run_in_executor(
                None,
                lambda: service.execute_llm(
                    prompt=request.prompt,
                    provider=provider,
                    model=model,
                    timeout=3600,
                    parse_json=parse_json,
                    enable_tools=enable_tools,
                    cli_options=cli_options,
                    profile=selected_profile,
                )
            )

            if result["success"]:
                stop_reason = "completed"
                normalized_result = result.get("result")
                raw_response = result.get("raw_response", "")
                claude_session_id = result.get("claude_session_id")

                # caller_type별 결과 저장
                save_success = True
                failure_reason = None
                if caller_type == "instagram":
                    if instagram_payload_has_mojibake(normalized_result, raw_response):
                        failure_reason = "encoding_mojibake"
                        save_success = False
                        logger.error(
                            "Instagram mojibake 감지: request_id=%s caller_id=%s session_id=%s payload=%s raw=%s",
                            request_id,
                            caller_id,
                            claude_session_id,
                            _truncate_for_log(normalized_result),
                            _truncate_for_log(raw_response),
                        )
                    else:
                        save_success = save_instagram_result(db, int(caller_id), normalized_result)
                elif caller_type == "universal_crawl":
                    save_success = save_universal_crawl_result(db, int(caller_id), normalized_result)
                elif caller_type == "topic_extract":
                    service.mark_completed(
                        request_id,
                        normalized_result,
                        raw_response,
                        claude_session_id,
                    )
                    self._increment_processed()
                    logger.info(f"LLM 실행 완료: id={request_id}")
                    save_success = save_topic_extract_result(db, caller_id, normalized_result)
                elif caller_type == "writing":
                    service.mark_completed(
                        request_id,
                        normalized_result,
                        raw_response,
                        claude_session_id,
                    )
                    self._increment_processed()
                    logger.info(f"LLM 실행 완료: id={request_id}")
                    save_success = save_writing_result(db, request, result)
                elif caller_type == "writing_generate":
                    service.mark_completed(
                        request_id,
                        normalized_result,
                        raw_response,
                        claude_session_id,
                    )
                    self._increment_processed()
                    logger.info(f"LLM 실행 완료: id={request_id}")
                    save_success = save_writing_generate_result(db, request, result)
                elif caller_type == "writing_refine":
                    service.mark_completed(
                        request_id,
                        normalized_result,
                        raw_response,
                        claude_session_id,
                    )
                    self._increment_processed()
                    logger.info(f"LLM 실행 완료: id={request_id}")
                    save_success = save_writing_refine_result(db, request, result)
                elif caller_type == "event_import":
                    save_success = save_event_import_result(db, request, result)
                elif caller_type == "report":
                    service.mark_completed(
                        request_id,
                        normalized_result,
                        raw_response,
                        claude_session_id,
                    )
                    self._increment_processed()
                    logger.info(f"LLM 실행 완료: id={request_id}")
                    save_success = save_report_result(db, request, result)
                elif caller_type == "pytest_fix":
                    service.mark_completed(
                        request_id,
                        normalized_result,
                        raw_response,
                        claude_session_id,
                    )
                    self._increment_processed()
                    logger.info(f"LLM 실행 완료: id={request_id}")
                    save_success = save_pytest_fix_result(db, request, result)
                elif caller_type == "plan_archive_analyze":
                    service.mark_completed(
                        request_id,
                        normalized_result,
                        raw_response,
                        claude_session_id,
                    )
                    self._increment_processed()
                    logger.info(f"LLM 실행 완료: id={request_id}")
                    save_outcome = save_plan_archive_result_outcome(db, request, result)
                    try:
                        outcome_cli_options = cli_options if isinstance(cli_options, dict) else {}
                        outcome_cli_options = dict(outcome_cli_options)
                        outcome_cli_options["plan_archive_save_outcome"] = {
                            "saved": bool(save_outcome.saved),
                            "status": save_outcome.status,
                            "reason": save_outcome.reason,
                            "record_id": save_outcome.record_id,
                        }
                        request.cli_options = json.dumps(outcome_cli_options, ensure_ascii=False)
                        db.add(request)
                        db.commit()
                    except Exception as exc:
                        db.rollback()
                        logger.warning(
                            "Plan Archive save outcome snapshot failed: id=%s error=%s",
                            request_id,
                            exc,
                        )
                    if save_outcome.status == "stale_skipped":
                        save_success = True
                        logger.info(
                            "Plan Archive stale result skipped without failing request: "
                            "id=%s record_id=%s reason=%s",
                            request_id,
                            save_outcome.record_id,
                            save_outcome.reason,
                        )
                    else:
                        save_success = save_outcome.saved
                        if not save_success:
                            failure_reason = (
                                f"Save result failed for {caller_type}: "
                                f"{save_outcome.status}"
                            )
                elif caller_type == "plan_recurrence_check":
                    service.mark_completed(
                        request_id,
                        normalized_result,
                        raw_response,
                        claude_session_id,
                    )
                    self._increment_processed()
                    logger.info(f"LLM 실행 완료: id={request_id}")
                    save_success = save_recurrence_check_result(db, request, result)
                elif caller_type == "plan_recurrence_suggest":
                    service.mark_completed(
                        request_id,
                        normalized_result,
                        raw_response,
                        claude_session_id,
                    )
                    self._increment_processed()
                    logger.info(f"LLM 실행 완료: id={request_id}")
                    save_success = save_recurrence_suggest_result(db, request, result)
                else:
                    service.mark_completed(
                        request_id,
                        normalized_result,
                        raw_response,
                        claude_session_id,
                    )
                    self._increment_processed()
                    logger.info(f"LLM 실행 완료: id={request_id}")

                if caller_type in {"instagram", "universal_crawl", "event_import"}:
                    if save_success:
                        service.prepare_completed(
                            request_id,
                            normalized_result,
                            raw_response,
                            claude_session_id,
                        )
                        db.commit()
                        self._increment_processed()
                        logger.info(f"LLM 실행 완료: id={request_id}")
                    else:
                        db.rollback()

                if not save_success:
                    payload_summary = _truncate_for_log(normalized_result)
                    response_summary = _truncate_for_log(raw_response)
                    logger.error(
                        "결과 저장 실패: id=%s, caller_type=%s, session_id=%s, payload=%s, raw=%s",
                        request_id,
                        caller_type,
                        claude_session_id,
                        payload_summary,
                        response_summary,
                    )
                    self._mark_request_failed_safely(
                        service,
                        db,
                        request_id,
                        failure_reason or f"Save result failed for {caller_type}",
                        raw_response,
                    )
            else:
                # JSON 파싱 실패지만 raw_response가 있는 경우
                if "raw_response" in result and result.get("raw_response"):
                    # writing_generate, writing_refine, report의 경우 raw_response만으로도 성공 처리
                    if caller_type in ["writing_generate", "writing_refine", "report", "test", "pytest_fix"]:
                        logger.info(f"JSON 파싱 실패했지만 raw_response 사용: id={request_id}")

                        # 빈 result dict로 결과 재구성
                        fallback_result = {
                            "success": True,
                            "result": {},
                            "raw_response": result.get("raw_response", "")
                        }

                        service.mark_completed(
                            request_id,
                            {},  # 빈 결과
                            result.get("raw_response", ""),
                            result.get("claude_session_id"),
                        )
                        self._increment_processed()
                        logger.info(f"LLM 실행 완료 (JSON 없음, raw_response 사용): id={request_id}")

                        # caller_type별 결과 저장
                        save_success = True
                        if caller_type == "writing_generate":
                            save_success = save_writing_generate_result(db, request, fallback_result)
                        elif caller_type == "writing_refine":
                            save_success = save_writing_refine_result(db, request, fallback_result)
                        elif caller_type == "report":
                            save_success = save_report_result(db, request, fallback_result)
                        elif caller_type == "pytest_fix":
                            save_success = save_pytest_fix_result(db, request, fallback_result)
                        elif request.caller_type == "plan_archive_insight_batch":
                            save_success = save_plan_archive_insight_result(db, request, fallback_result)

                        if not save_success:
                            logger.error(f"결과 저장 실패 (fallback 경로, 상태 전환: completed -> failed): id={request_id}, caller_type={caller_type}")
                            self._mark_request_failed_safely(
                                service,
                                db,
                                request_id,
                                f"Save result failed for {caller_type} (fallback)",
                            )
                    else:
                        # Quota 에러 감지 및 provider pause 설정
                        quota_retry_ms = result.get("quota_retry_ms")
                        if quota_retry_ms is not None:
                            if selected_profile is not None:
                                paused_until = service.set_profile_quota_pause(
                                    provider, selected_profile.name, quota_retry_ms, reason=result.get("error", "")
                                )
                            else:
                                paused_until = service.set_provider_quota_pause(
                                    provider, quota_retry_ms, reason=result.get("error", "")
                                )
                            logger.warning(f"[QUOTA] {provider} 쿼터 소진. {paused_until}까지 일시중지")
                            # O-4: registry quota state 자동 갱신
                            try:
                                _registry_report_quota(
                                    provider, model if model else None,
                                    weekly_used_pct=100,
                                    short_cooldown_minutes=max(1, quota_retry_ms // 60000),
                                    source="auto_quota_detect",
                                )
                            except Exception as _e:
                                logger.warning(f"[auto_quota_detect] registry 갱신 실패: {_e}")

                        # 다른 타입은 실패 처리 (raw_response 보존)
                        self._mark_request_failed_safely(
                            service,
                            db,
                            request_id,
                            result["error"],
                            result.get("raw_response", ""),
                        )
                        stop_reason = "quota_paused" if quota_retry_ms is not None else "failed"
                        error_summary = result.get("error")
                        self._increment_error()
                        logger.warning(f"LLM 실행 실패: {result['error']}")

                        # caller_type별 실패 표시
                        if caller_type == "instagram":
                            mark_instagram_failed(db, int(caller_id), result["error"])
                        elif caller_type == "universal_crawl":
                            mark_universal_crawl_failed(db, int(caller_id), result["error"])
                        elif caller_type == "writing":
                            mark_writing_failed(db, request, result["error"])
                else:
                    # Quota 에러 감지 및 provider pause 설정
                    quota_retry_ms = result.get("quota_retry_ms")
                    if quota_retry_ms is not None:
                        if selected_profile is not None:
                            paused_until = service.set_profile_quota_pause(
                                provider, selected_profile.name, quota_retry_ms, reason=result.get("error", "")
                            )
                        else:
                            paused_until = service.set_provider_quota_pause(
                                provider, quota_retry_ms, reason=result.get("error", "")
                            )
                        logger.warning(f"[QUOTA] {provider} 쿼터 소진. {paused_until}까지 일시중지")
                        # O-4: registry quota state 자동 갱신
                        try:
                            _registry_report_quota(
                                provider, model if model else None,
                                weekly_used_pct=100,
                                short_cooldown_minutes=max(1, quota_retry_ms // 60000),
                                source="auto_quota_detect",
                            )
                        except Exception as _e:
                            logger.warning(f"[auto_quota_detect] registry 갱신 실패: {_e}")

                    # raw_response도 없으면 실패 처리
                    self._mark_request_failed_safely(service, db, request_id, result["error"])
                    stop_reason = "quota_paused" if quota_retry_ms is not None else "failed"
                    error_summary = result.get("error")
                    self._increment_error()
                    logger.warning(f"LLM 실행 실패: {result['error']}")

                    # caller_type별 실패 표시
                    if caller_type == "instagram":
                        mark_instagram_failed(db, int(caller_id), result["error"])
                    elif caller_type == "universal_crawl":
                        mark_universal_crawl_failed(db, int(caller_id), result["error"])
                    elif caller_type == "writing":
                        mark_writing_failed(db, request, result["error"])

        except Exception as e:
            self._mark_request_failed_safely(service, db, request_id, str(e))
            error_summary = str(e)
            self._increment_error()
            logger.error(f"LLM 실행 예외: {e}", exc_info=True)
        finally:
            if claim_acquired and claim_service is not None:
                try:
                    claim_service.release(
                        request_id,
                        stop_reason=stop_reason,
                        error_summary=error_summary,
                    )
                except Exception as e:
                    logger.warning("[PROFILE-CLAIM] release 실패: request=%s error=%s", request_id, e)
            if caller_type == "plan_archive_analyze":
                try:
                    from app.modules.dev_runner.services.plan_archive_execution_service import (
                        PlanArchiveExecutionService,
                    )

                    PlanArchiveExecutionService(db).sync_attempt_for_request_id(request_id)
                except Exception as e:
                    logger.warning("[PLAN-ARCHIVE-EXEC] final sync 실패: request=%s error=%s", request_id, e)
            self._update_worker_state("idle")
            # 대기 중인 요청이 있으면 즉시 처리하도록 이벤트 설정
            self.continue_event.set()


# 전역 워커 인스턴스
worker_instance: LLMWorker = None


def handle_exception(loop, context):
    """asyncio 예외 핸들러."""
    msg = context.get("exception", context.get("message", "Unknown error"))
    task = context.get("task")

    if task:
        logger.error(f"[ASYNC-ERROR] 처리되지 않은 예외 (task: {task.get_name()}): {msg}")
    else:
        logger.error(f"[ASYNC-ERROR] 처리되지 않은 예외: {msg}")

    exception = context.get("exception")
    if exception:
        import traceback
        tb_str = ''.join(traceback.format_exception(type(exception), exception, exception.__traceback__))
        logger.error(f"[ASYNC-ERROR] Traceback:\n{tb_str}")


async def main():
    """워커 메인 함수."""
    global worker_instance

    loop = asyncio.get_running_loop()
    loop.set_exception_handler(handle_exception)

    logger.info("=" * 50)
    logger.info("Claude LLM 워커 프로세스 시작")
    logger.info(f"PID: {os.getpid()}")
    logger.info(f"Python 버전: {sys.version}")
    logger.info("=" * 50)

    worker_instance = LLMWorker()

    def signal_handler(signum, frame):
        logger.info(f"종료 시그널 수신: {signum}")
        asyncio.create_task(worker_instance.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await worker_instance.start()
    except asyncio.CancelledError:
        logger.info("워커 태스크 취소됨")
    except Exception as e:
        logger.critical(f"워커 치명적 오류: {e}", exc_info=True)
        if worker_instance:
            try:
                await worker_instance.stop()
            except Exception:
                pass
        sys.exit(1)
    finally:
        logger.info("LLM 워커 프로세스 종료")


if __name__ == "__main__":
    asyncio.run(main())

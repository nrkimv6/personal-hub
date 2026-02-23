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
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# 비동기 로거 설정
from app.utils.async_logger import AsyncLoggerManager

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
            logger.warning(f"Instagram post not found: {post_id}")
            return False

        # 이벤트 기간 파싱
        event_period = llm_result.get("event_period")
        event_start = None
        event_end = None
        if event_period and isinstance(event_period, dict):
            event_start = parse_date(event_period.get("start"))
            event_end = parse_date(event_period.get("end"))

        # 발표일 파싱
        announcement_date = parse_date(llm_result.get("announcement_date"))

        # 분류 태그에 따라 적절한 테이블에 레코드 생성
        tag = llm_result.get("tag")
        llm_urls = llm_result.get("urls") or []
        location = llm_result.get("location") or {}

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

        # 리그램/후기 등 분류 테이블 생성이 필요없는 태그는 classified_type/id가 NULL로 유지됨

        db.commit()
        logger.info(f"Instagram post {post_id} LLM result saved: tag={tag}")
        return True

    except Exception as e:
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

        db.commit()
        logger.info(f"CrawledPage {page_id} LLM result saved: is_event={is_event}, is_popup={is_popup}")
        return True

    except Exception as e:
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
                    is_active=1,
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

            refine_request = LLMRequest(
                caller_type="writing_refine",
                caller_id=str(writing.id),
                prompt=refine_prompt,
                status="pending",
                requested_by="auto",
                request_source="writing_worker",
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
        db.commit()
        db.refresh(event)

        logger.info(f"Event 생성 완료: id={event.id}, title={event.title}")
        return True

    except Exception as e:
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
                        is_active=1,
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
        """하트비트 업데이트."""
        if not self.worker_id:
            return

        db = SessionLocal()
        try:
            service = LLMService(db)
            service.update_heartbeat(self.worker_id)
        except Exception as e:
            logger.warning(f"Heartbeat 업데이트 실패: {e}")
        finally:
            db.close()

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
                # Heartbeat 업데이트
                self._update_heartbeat()

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

    async def _process_pending_requests(self):
        """Pending 요청 처리 (우선순위 큐 기반)."""
        db = SessionLocal()
        try:
            service = LLMService(db)
            request = service.get_next_request()

            if request:
                logger.info(
                    f"Pending 요청 발견: id={request.id}, queue={request.queue_name}, "
                    f"caller={request.caller_type}:{request.caller_id}"
                )
                await self._execute_request(request, db, service)

        except Exception as e:
            logger.error(f"Pending 요청 처리 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _execute_request(
        self,
        request: LLMRequest,
        db,
        service: LLMService,
    ):
        """LLM 요청 실행."""
        try:
            # 처리 중으로 변경
            service.mark_processing(request.id)
            self._update_worker_state("processing", request.id)

            logger.info(f"LLM 실행 시작: id={request.id}, queue={request.queue_name}, caller_type={request.caller_type}")

            # cli_options 파싱 (JSON 문자열 → dict)
            cli_options = None
            if getattr(request, "cli_options", None):
                try:
                    cli_options = json.loads(request.cli_options)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"cli_options 파싱 실패: id={request.id}")

            # caller_type에 따라 도구 활성화 결정
            # - instagram, universal_crawl: Read 도구로 이미지 분석 가능
            # - image_classify: cli_options에서 allowed_tools 지정
            # - writing 관련: 도구 사용 금지 (도구 사용 시 글 작성 대신 프롬프트 분석만 함)
            enable_tools = request.caller_type in ["instagram", "universal_crawl"]

            # provider/model 읽기 (기본값: claude, "")
            provider = getattr(request, "provider", None) or "claude"
            model = getattr(request, "model", None) or ""

            # LLM 실행 (비동기 실행을 위해 run_in_executor 사용)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: service.execute_llm(
                    prompt=request.prompt,
                    provider=provider,
                    model=model,
                    enable_tools=enable_tools,
                    cli_options=cli_options,
                )
            )

            if result["success"]:
                service.mark_completed(
                    request.id,
                    result["result"],
                    result.get("raw_response", ""),
                )
                self._increment_processed()
                logger.info(f"LLM 실행 완료: id={request.id}")

                # caller_type별 결과 저장
                if request.caller_type == "instagram":
                    save_instagram_result(db, int(request.caller_id), result["result"])
                elif request.caller_type == "universal_crawl":
                    save_universal_crawl_result(db, int(request.caller_id), result["result"])
                elif request.caller_type == "topic_extract":
                    save_topic_extract_result(db, request.caller_id, result["result"])
                elif request.caller_type == "writing":
                    save_writing_result(db, request, result)
                elif request.caller_type == "writing_generate":
                    save_writing_generate_result(db, request, result)
                elif request.caller_type == "writing_refine":
                    save_writing_refine_result(db, request, result)
                elif request.caller_type == "event_import":
                    save_event_import_result(db, request, result)
                elif request.caller_type == "report":
                    save_report_result(db, request, result)
            else:
                # JSON 파싱 실패지만 raw_response가 있는 경우
                if "raw_response" in result and result.get("raw_response"):
                    # writing_generate, writing_refine, report의 경우 raw_response만으로도 성공 처리
                    if request.caller_type in ["writing_generate", "writing_refine", "report"]:
                        logger.info(f"JSON 파싱 실패했지만 raw_response 사용: id={request.id}")

                        # 빈 result dict로 결과 재구성
                        fallback_result = {
                            "success": True,
                            "result": {},
                            "raw_response": result.get("raw_response", "")
                        }

                        service.mark_completed(
                            request.id,
                            {},  # 빈 결과
                            result.get("raw_response", ""),
                        )
                        self._increment_processed()
                        logger.info(f"LLM 실행 완료 (JSON 없음, raw_response 사용): id={request.id}")

                        # caller_type별 결과 저장
                        if request.caller_type == "writing_generate":
                            save_writing_generate_result(db, request, fallback_result)
                        elif request.caller_type == "writing_refine":
                            save_writing_refine_result(db, request, fallback_result)
                        elif request.caller_type == "report":
                            save_report_result(db, request, fallback_result)
                    else:
                        # 다른 타입은 실패 처리
                        service.mark_failed(request.id, result["error"])
                        self._increment_error()
                        logger.warning(f"LLM 실행 실패: {result['error']}")

                        # caller_type별 실패 표시
                        if request.caller_type == "instagram":
                            mark_instagram_failed(db, int(request.caller_id), result["error"])
                        elif request.caller_type == "universal_crawl":
                            mark_universal_crawl_failed(db, int(request.caller_id), result["error"])
                        elif request.caller_type == "writing":
                            mark_writing_failed(db, request, result["error"])
                else:
                    # raw_response도 없으면 실패 처리
                    service.mark_failed(request.id, result["error"])
                    self._increment_error()
                    logger.warning(f"LLM 실행 실패: {result['error']}")

                    # caller_type별 실패 표시
                    if request.caller_type == "instagram":
                        mark_instagram_failed(db, int(request.caller_id), result["error"])
                    elif request.caller_type == "universal_crawl":
                        mark_universal_crawl_failed(db, int(request.caller_id), result["error"])
                    elif request.caller_type == "writing":
                        mark_writing_failed(db, request, result["error"])

        except Exception as e:
            service.mark_failed(request.id, str(e))
            self._increment_error()
            logger.error(f"LLM 실행 예외: {e}", exc_info=True)
        finally:
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

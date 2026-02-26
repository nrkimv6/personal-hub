"""
Universal Crawl Analyzer 서비스 - 웹페이지 AI 분석 서비스

Instagram LLMClassifierService를 참고하여 구현됨.
"""
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.universal_crawl import CrawledPage
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.models.llm_request import LLMRequest

logger = logging.getLogger(__name__)

# 프롬프트 템플릿 (이벤트/경품 행사 감지용)
ANALYSIS_PROMPT = """다음 웹페이지 내용을 분석하여 이벤트/경품 행사인지 판별해주세요.

## 페이지 정보
- 제목: {title}
- URL: {url}
- URL 타입: {url_type}

## 페이지 본문
{content}

## 판별 기준
- **이벤트**: 응모/참여하면 경품을 받을 수 있는 행사 (설문조사, 구글폼 등 포함)
- **미분류**: 이벤트가 아닌 일반 페이지

## 이벤트가 아닌 것 (중요!)
- 단순 정보 페이지 (뉴스, 블로그 포스트 등)
- 상품 판매/구매 페이지
- 회원가입/로그인 페이지
- 이벤트 종료 후 결과 발표 페이지

## 응답 형식 (JSON)
```json
{{
    "is_event": true,
    "event_type": "giveaway|survey|form|other",
    "confidence": 0.85,
    "prizes": ["경품1", "경품2"],
    "winner_count": 10,
    "deadline": "2025-01-31",
    "organizer": "주최사/브랜드명",
    "summary": "이벤트 핵심 내용 요약 (50자 이내)"
}}
```

## 필드 설명
- is_event: 이벤트 여부 (true/false)
- event_type: 이벤트 유형 (giveaway: 경품추첨, survey: 설문조사, form: 구글폼/네이버폼, other: 기타)
- confidence: 판별 신뢰도 (0.0 ~ 1.0)
- prizes: 경품 목록 (배열, 없으면 빈 배열)
- winner_count: 당첨자 수 (숫자, 모르면 null)
- deadline: 마감일 (YYYY-MM-DD 형식, 모르면 null)
- organizer: 주최사/브랜드명 (모르면 null)
- summary: 한줄 요약

값을 알 수 없으면 null로 표시하세요.
반드시 JSON 형식으로만 응답하세요."""


class UniversalCrawlAnalyzerService:
    """웹페이지 AI 분석 서비스."""

    CALLER_TYPE = "universal_crawl"

    def __init__(self, db: Session):
        self.db = db
        self._llm_service = LLMService(db)

    def create_analysis_request(
        self,
        page_id: int,
        requested_by: str = "manual",
    ) -> Optional[LLMRequest]:
        """건별 AI 분석 요청 생성.

        Args:
            page_id: CrawledPage ID
            requested_by: 요청자 ('auto' 또는 'manual')

        Returns:
            생성된 LLMRequest 또는 None
        """
        # 페이지 조회
        page = self.db.query(CrawledPage).filter(CrawledPage.id == page_id).first()
        if not page:
            logger.warning(f"CrawledPage {page_id} not found")
            return None

        # 이미 pending/processing 상태인 요청이 있는지 확인
        existing = (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.caller_type == self.CALLER_TYPE,
                LLMRequest.caller_id == str(page_id),
                LLMRequest.status.in_(["pending", "processing"]),
                LLMRequest.deleted_at.is_(None),
            )
            .first()
        )

        if existing:
            logger.info(f"이미 분석 요청 존재: page_id={page_id}, request_id={existing.id}")
            return existing

        # 프롬프트 생성
        content = page.content or page.description or ""
        if len(content) > 5000:
            content = content[:5000] + "... (내용 생략)"

        prompt = ANALYSIS_PROMPT.format(
            title=page.title or page.og_title or "(제목 없음)",
            url=page.url,
            url_type=page.url_type,
            content=content,
        )

        # quota pause 경고 로그
        provider = "claude"
        paused_until = self._llm_service.get_provider_quota_pause(provider)
        if paused_until:
            logger.warning(
                "[QUOTA_WARN] universal_crawl 요청 — %s 쿼터 정지 중 (재개: %s), 큐에 추가됨",
                provider,
                paused_until.isoformat(),
            )

        # LLM 요청 생성
        request = self._llm_service.enqueue(
            caller_type=self.CALLER_TYPE,
            caller_id=str(page_id),
            prompt=prompt,
            requested_by=requested_by,
            request_source=f"universal_crawl_{page.url_type}",
        )

        logger.info(f"AI 분석 요청 생성: page_id={page_id}, request_id={request.id}")
        return request

    def get_pending_request(self, page_id: int) -> Optional[LLMRequest]:
        """페이지에 대한 pending/processing 요청 조회.

        Args:
            page_id: CrawledPage ID

        Returns:
            LLMRequest 또는 None
        """
        return (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.caller_type == self.CALLER_TYPE,
                LLMRequest.caller_id == str(page_id),
                LLMRequest.status.in_(["pending", "processing"]),
                LLMRequest.deleted_at.is_(None),
            )
            .first()
        )

    def get_result(self, page_id: int) -> Optional[dict]:
        """페이지의 AI 분석 결과 조회.

        Args:
            page_id: CrawledPage ID

        Returns:
            분석 결과 또는 None
        """
        request = self._llm_service.get_result(self.CALLER_TYPE, str(page_id))
        if not request:
            return None

        result = None
        if request.result:
            try:
                result = json.loads(request.result)
            except json.JSONDecodeError:
                pass

        return {
            "id": request.id,
            "page_id": page_id,
            "status": request.status,
            "result": result,
            "error_message": request.error_message,
            "requested_at": request.requested_at,
            "processed_at": request.processed_at,
        }

    def get_pending_count(self) -> int:
        """Universal Crawl 관련 대기 중인 요청 수."""
        return (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.caller_type == self.CALLER_TYPE,
                LLMRequest.status == "pending",
            )
            .count()
        )

    def get_stats(self) -> dict:
        """Universal Crawl AI 분석 통계 조회."""
        base_query = self.db.query(LLMRequest).filter(
            LLMRequest.caller_type == self.CALLER_TYPE
        )

        total = base_query.count()
        pending = (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.caller_type == self.CALLER_TYPE,
                LLMRequest.status == "pending",
            )
            .count()
        )
        processing = (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.caller_type == self.CALLER_TYPE,
                LLMRequest.status == "processing",
            )
            .count()
        )
        completed = (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.caller_type == self.CALLER_TYPE,
                LLMRequest.status == "completed",
            )
            .count()
        )
        failed = (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.caller_type == self.CALLER_TYPE,
                LLMRequest.status == "failed",
            )
            .count()
        )

        return {
            "total": total,
            "pending": pending,
            "processing": processing,
            "completed": completed,
            "failed": failed,
        }

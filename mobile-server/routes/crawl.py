"""
구조화 크롤링 API

파싱 규칙을 적용하여 아이템을 추출하는 엔드포인트입니다.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import logging

from parser import ParseConfig, ParseResult, MockParser

logger = logging.getLogger(__name__)

router = APIRouter()


# ============= 스키마 =============

class CrawlRequest(BaseModel):
    """크롤링 요청"""
    url: str = Field(..., description="크롤링 대상 URL")
    parse_config: Dict[str, Any] = Field(..., description="파싱 설정 JSON")
    use_pagination: bool = Field(False, description="페이지네이션 사용 여부")


class CrawlResponse(BaseModel):
    """크롤링 응답"""
    success: bool = Field(..., description="성공 여부")
    items: List[Dict[str, Any]] = Field(default_factory=list, description="추출된 아이템 목록")
    total_count: int = Field(0, description="총 아이템 수")
    pages_crawled: int = Field(1, description="크롤링한 페이지 수")
    errors: List[str] = Field(default_factory=list, description="에러 목록")
    fetched_at: str = Field(..., description="수집 시각")


# ============= API 엔드포인트 =============

@router.post("/crawl", response_model=CrawlResponse)
async def crawl_page(request: CrawlRequest):
    """
    구조화 크롤링 실행

    파싱 설정에 따라 페이지에서 아이템을 추출합니다.
    현재는 Mock 파서를 사용하여 샘플 데이터를 반환합니다.

    Phase 1-2 완료 후 실제 브라우저 기반 파서로 전환할 수 있습니다.
    """
    try:
        from datetime import datetime

        # ParseConfig 객체 생성
        try:
            config = ParseConfig(**request.parse_config)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"파싱 설정이 올바르지 않습니다: {str(e)}"
            )

        # Mock 파서 생성
        parser = MockParser(config)

        # 파싱 실행
        if request.use_pagination and config.pagination:
            result: ParseResult = await parser.parse_multiple_pages(
                start_url=request.url,
                max_pages=config.pagination.max_pages
            )
        else:
            # 단일 페이지 크롤링 (Mock HTML 사용)
            mock_html = """
            <div class="product-list">
                <div class="product-card">
                    <img src="/images/sample1.jpg" class="product-image">
                    <h3 class="product-title">샘플 상품 1</h3>
                    <span class="price">99,000원</span>
                    <a href="/products/1" class="detail-link">상세보기</a>
                </div>
                <div class="product-card">
                    <img src="/images/sample2.jpg" class="product-image">
                    <h3 class="product-title">샘플 상품 2</h3>
                    <span class="price">149,000원</span>
                    <a href="/products/2" class="detail-link">상세보기</a>
                </div>
            </div>
            """
            result = await parser.parse_html(mock_html, request.url)

        # 응답 생성
        return CrawlResponse(
            success=len(result.errors) == 0,
            items=[item.model_dump() for item in result.items],
            total_count=result.total_count,
            pages_crawled=result.pages_crawled,
            errors=result.errors,
            fetched_at=datetime.utcnow().isoformat() + "Z"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"크롤링 실패: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"크롤링 중 오류가 발생했습니다: {str(e)}"
        )

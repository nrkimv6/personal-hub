"""
Mock 파서 구현

샘플 HTML을 파싱하는 테스트용 파서입니다.
실제 브라우저 없이도 파싱 로직을 테스트할 수 있습니다.
"""
from typing import Optional, List
from bs4 import BeautifulSoup
import logging

from .base import PageParser
from .types import ParseConfig, ParseResult, ParsedItem

logger = logging.getLogger(__name__)


class MockParser(PageParser):
    """
    Mock 파서

    BeautifulSoup을 사용하여 HTML을 파싱합니다.
    실제 브라우저 제어 없이 샘플 데이터로 테스트할 수 있습니다.
    """

    async def parse_html(self, html: str, base_url: Optional[str] = None) -> ParseResult:
        """
        HTML을 파싱하여 아이템 목록 추출

        Args:
            html: HTML 문자열
            base_url: 상대 URL 해석을 위한 기준 URL

        Returns:
            ParseResult: 파싱 결과
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')
            items: List[ParsedItem] = []
            errors: List[str] = []

            # 컨테이너 요소들 찾기
            containers = soup.select(self.config.container_selector)

            if not containers:
                logger.warning(f"컨테이너 '{self.config.container_selector}'를 찾을 수 없습니다.")
                errors.append(f"컨테이너 '{self.config.container_selector}'를 찾을 수 없습니다.")

            for container in containers:
                try:
                    item = await self._extract_item(container, base_url)
                    items.append(item)
                except Exception as e:
                    error_msg = f"아이템 추출 실패: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)

            return ParseResult(
                items=items,
                total_count=len(items),
                pages_crawled=1,
                errors=errors,
                metadata={
                    "parser": "MockParser",
                    "container_count": len(containers)
                }
            )

        except Exception as e:
            logger.error(f"HTML 파싱 실패: {str(e)}")
            return ParseResult(
                items=[],
                total_count=0,
                pages_crawled=0,
                errors=[f"HTML 파싱 실패: {str(e)}"]
            )

    async def _extract_item(self, container, base_url: Optional[str]) -> ParsedItem:
        """
        단일 아이템 추출

        Args:
            container: BeautifulSoup 컨테이너 요소
            base_url: 기준 URL

        Returns:
            ParsedItem: 추출된 아이템
        """
        extracted_attrs = {}
        title = ""
        item_url = None
        image_url = None

        for attr_name, attr_config in self.config.attributes.items():
            try:
                element = container.select_one(attr_config.selector)

                if not element:
                    extracted_attrs[attr_name] = None
                    continue

                if attr_config.type == "text":
                    value = element.get_text(strip=True)
                elif attr_config.type == "attr" and attr_config.attr:
                    value = element.get(attr_config.attr)
                    # URL 정규화
                    if attr_config.attr in ['href', 'src'] and value:
                        value = self._normalize_url(value, base_url)
                else:
                    value = None

                extracted_attrs[attr_name] = value

                # 특별 필드 매핑
                if attr_name == 'title' and value:
                    title = str(value)
                elif attr_name in ['link', 'url', 'item_url'] and value:
                    item_url = str(value)
                elif attr_name in ['image', 'image_url', 'thumbnail'] and value:
                    image_url = str(value)

            except Exception as e:
                logger.warning(f"속성 '{attr_name}' 추출 실패: {str(e)}")
                extracted_attrs[attr_name] = None

        return ParsedItem(
            title=title,
            item_url=item_url,
            image_url=image_url,
            attributes=extracted_attrs,
            raw_html=str(container)[:500]  # 처음 500자만 저장
        )

    async def parse_multiple_pages(
        self,
        start_url: str,
        max_pages: Optional[int] = None
    ) -> ParseResult:
        """
        여러 페이지 파싱 (Mock 구현)

        실제로는 Mock 데이터를 반복해서 반환합니다.
        실제 구현에서는 브라우저로 다음 페이지를 탐색합니다.

        Args:
            start_url: 시작 URL
            max_pages: 최대 페이지 수

        Returns:
            ParseResult: 통합된 결과
        """
        max_pages = max_pages or (self.config.pagination.max_pages if self.config.pagination else 1)

        logger.info(f"Mock 다중 페이지 파싱: {start_url}, 최대 {max_pages}페이지")

        # Mock 샘플 HTML
        sample_html = """
        <div class="product-list">
            <div class="product-card">
                <img src="/images/mock-product.jpg" class="product-image" alt="Mock Product">
                <h3 class="product-title">Mock Product {page}</h3>
                <span class="price">99,000원</span>
                <a href="/products/mock-{page}" class="detail-link">상세보기</a>
            </div>
        </div>
        """

        all_items: List[ParsedItem] = []
        all_errors: List[str] = []

        for page_num in range(1, max_pages + 1):
            html = sample_html.replace("{page}", str(page_num))
            result = await self.parse_html(html, start_url)

            all_items.extend(result.items)
            all_errors.extend(result.errors)

            logger.info(f"페이지 {page_num}/{max_pages}: {len(result.items)}개 아이템 추출")

        return ParseResult(
            items=all_items,
            total_count=len(all_items),
            pages_crawled=max_pages,
            errors=all_errors,
            metadata={
                "parser": "MockParser",
                "mode": "multi-page"
            }
        )

"""
파서 기본 클래스

PageParser 추상 클래스를 정의합니다.
실제 구현은 MockParser, RealParser 등으로 확장할 수 있습니다.
"""
from abc import ABC, abstractmethod
from typing import Optional
from .types import ParseConfig, ParseResult


class PageParser(ABC):
    """
    페이지 파서 추상 클래스

    HTML을 파싱하여 구조화된 아이템을 추출하는 인터페이스를 정의합니다.
    """

    def __init__(self, config: ParseConfig):
        """
        Args:
            config: 파싱 설정
        """
        self.config = config

    @abstractmethod
    async def parse_html(self, html: str, base_url: Optional[str] = None) -> ParseResult:
        """
        HTML을 파싱하여 아이템 목록 추출

        Args:
            html: HTML 문자열
            base_url: 상대 URL 해석을 위한 기준 URL

        Returns:
            ParseResult: 파싱 결과
        """
        pass

    @abstractmethod
    async def parse_multiple_pages(
        self,
        start_url: str,
        max_pages: Optional[int] = None
    ) -> ParseResult:
        """
        여러 페이지를 순회하며 파싱 (페이지네이션 처리)

        Args:
            start_url: 시작 URL
            max_pages: 최대 페이지 수 (None이면 config의 설정 사용)

        Returns:
            ParseResult: 통합된 파싱 결과
        """
        pass

    def _normalize_url(self, url: Optional[str], base_url: Optional[str]) -> Optional[str]:
        """
        상대 URL을 절대 URL로 변환

        Args:
            url: 변환할 URL
            base_url: 기준 URL

        Returns:
            정규화된 URL
        """
        if not url:
            return None

        if url.startswith('http://') or url.startswith('https://'):
            return url

        if not base_url:
            return url

        from urllib.parse import urljoin
        return urljoin(base_url, url)

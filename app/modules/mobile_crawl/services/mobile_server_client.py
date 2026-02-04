"""
모바일 서버 클라이언트

데스크톱 서버에서 모바일 서버의 API를 호출하는 클라이언트입니다.
"""
import httpx
import os
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class MobileServerClient:
    """모바일 서버 HTTP 클라이언트"""

    def __init__(self, base_url: Optional[str] = None, timeout: int = 60):
        """
        Args:
            base_url: 모바일 서버 URL (기본값: 환경변수 MOBILE_SERVER_URL)
            timeout: 요청 타임아웃 (초)
        """
        self.base_url = base_url or os.getenv("MOBILE_SERVER_URL", "http://localhost:8080")
        self.timeout = timeout
        logger.info(f"MobileServerClient 초기화: {self.base_url}")

    async def health_check(self) -> Dict[str, Any]:
        """
        모바일 서버 헬스체크

        Returns:
            헬스 정보 딕셔너리

        Raises:
            httpx.HTTPError: 연결 실패 또는 HTTP 에러
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self.base_url}/health")
            response.raise_for_status()
            return response.json()

    async def fetch_html(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        wait_timeout: int = 30000,
        screenshot: bool = False
    ) -> Dict[str, Any]:
        """
        Raw HTML 수집 요청

        Args:
            url: 수집할 URL
            wait_for_selector: 대기할 CSS 셀렉터
            wait_timeout: 대기 시간 (밀리초)
            screenshot: 스크린샷 캡처 여부

        Returns:
            {
                "html": str,
                "title": str,
                "final_url": str,
                "screenshot_base64": Optional[str],
                "fetched_at": str
            }

        Raises:
            httpx.HTTPError: 연결 실패 또는 HTTP 에러
        """
        payload = {
            "url": url,
            "wait_for_selector": wait_for_selector,
            "wait_timeout": wait_timeout,
            "screenshot": screenshot
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(f"모바일 서버에 HTML 수집 요청: {url}")
            response = await client.post(
                f"{self.base_url}/api/fetch-html",
                json=payload
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"HTML 수집 완료: {url} (길이: {len(result.get('html', ''))})")
            return result

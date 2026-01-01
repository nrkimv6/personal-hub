"""RSS 피드 수집기 - 티스토리, 네이버 블로그 등에서 글 수집."""

import hashlib
import logging
import re
from datetime import datetime
from typing import Optional

import feedparser
import httpx

logger = logging.getLogger(__name__)


class RSSCollector:
    """RSS 피드 수집기."""

    # 시니어 타겟 키워드
    SENIOR_KEYWORDS = [
        "에세이",
        "일상",
        "가족",
        "부모",
        "추억",
        "계절",
        "고향",
        "인생",
        "마음",
        "감사",
        "건강",
        "산책",
        "자연",
        "여행",
        "독서",
    ]

    # 제외 키워드 (젊은 세대/기술/광고)
    EXCLUDE_KEYWORDS = [
        "취준",
        "대학생",
        "20대",
        "MZ",
        "광고",
        "협찬",
        "쿠팡파트너스",
        "제휴",
        "할인코드",
    ]

    def __init__(self, timeout: float = 10.0):
        """초기화.

        Args:
            timeout: HTTP 요청 타임아웃 (초)
        """
        self.timeout = timeout

    async def fetch_feed(self, url: str) -> list[dict]:
        """RSS 피드에서 글 목록 가져오기.

        Args:
            url: RSS 피드 URL

        Returns:
            글 목록 (title, content, link, published, source)
        """
        try:
            # httpx로 피드 내용 가져오기 (feedparser는 동기라서)
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                content = response.text

            # feedparser로 파싱
            feed = feedparser.parse(content)

            if feed.bozo:
                # 파싱 에러가 있지만 entries가 있으면 계속 진행
                if not feed.entries:
                    logger.warning(f"RSS 파싱 실패: {url} - {feed.bozo_exception}")
                    return []

            results = []
            for entry in feed.entries:
                # 본문 추출 (summary 또는 content)
                content_text = self._extract_content(entry)

                if not content_text:
                    continue

                results.append(
                    {
                        "title": entry.get("title", "").strip(),
                        "content": content_text,
                        "link": entry.get("link", ""),
                        "published": self._parse_date(entry.get("published")),
                        "source": url,
                        "author": entry.get("author", ""),
                    }
                )

            logger.info(f"RSS 수집 완료: {url} - {len(results)}건")
            return results

        except httpx.HTTPError as e:
            logger.error(f"RSS HTTP 에러: {url} - {e}")
            return []
        except Exception as e:
            logger.error(f"RSS 수집 에러: {url} - {e}")
            return []

    def _extract_content(self, entry: dict) -> str:
        """RSS 엔트리에서 본문 추출 및 정제."""
        # content 필드 먼저 시도
        if "content" in entry and entry["content"]:
            raw = entry["content"][0].get("value", "")
        elif "summary" in entry:
            raw = entry.get("summary", "")
        else:
            return ""

        # HTML 태그 제거
        text = self._strip_html(raw)

        # 공백 정리
        text = re.sub(r"\s+", " ", text).strip()

        return text

    @staticmethod
    def _strip_html(text: str) -> str:
        """HTML 태그 제거."""
        # 스크립트/스타일 제거
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        # HTML 태그 제거
        text = re.sub(r"<[^>]+>", "", text)
        # HTML 엔티티 디코딩
        text = text.replace("&nbsp;", " ")
        text = text.replace("&amp;", "&")
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        text = text.replace("&quot;", '"')
        text = text.replace("&#39;", "'")
        return text

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
        """날짜 문자열 파싱."""
        if not date_str:
            return None
        try:
            # feedparser가 파싱한 시간 구조체 사용
            import time

            from email.utils import parsedate_to_datetime

            return parsedate_to_datetime(date_str)
        except Exception:
            return None

    def filter_by_length(
        self, items: list[dict], min_len: int = 300, max_len: int = 3000
    ) -> list[dict]:
        """글자 수로 필터링.

        Args:
            items: 글 목록
            min_len: 최소 글자 수
            max_len: 최대 글자 수

        Returns:
            필터링된 글 목록
        """
        return [
            item
            for item in items
            if item.get("content") and min_len <= len(item["content"]) <= max_len
        ]

    def filter_by_keywords(
        self,
        items: list[dict],
        include_keywords: Optional[list[str]] = None,
        exclude_keywords: Optional[list[str]] = None,
    ) -> list[dict]:
        """키워드로 필터링.

        Args:
            items: 글 목록
            include_keywords: 포함해야 할 키워드 (하나라도 있으면 통과)
            exclude_keywords: 제외할 키워드 (하나라도 있으면 제외)

        Returns:
            필터링된 글 목록
        """
        if include_keywords is None:
            include_keywords = self.SENIOR_KEYWORDS
        if exclude_keywords is None:
            exclude_keywords = self.EXCLUDE_KEYWORDS

        filtered = []
        for item in items:
            content = item.get("content", "").lower()
            title = item.get("title", "").lower()
            full_text = f"{title} {content}"

            # 제외 키워드 체크
            if any(kw.lower() in full_text for kw in exclude_keywords):
                continue

            # 포함 키워드 체크 (선택적)
            # 키워드 매칭 점수 계산
            score = sum(1 for kw in include_keywords if kw.lower() in full_text)
            item["relevance_score"] = score

            filtered.append(item)

        # 점수순 정렬
        return sorted(filtered, key=lambda x: x.get("relevance_score", 0), reverse=True)

    @staticmethod
    def compute_content_hash(content: str) -> str:
        """콘텐츠 해시 계산 (중복 체크용).

        Args:
            content: 글 본문

        Returns:
            SHA256 해시 (64자)
        """
        # 공백/줄바꿈 정규화 후 해시
        normalized = re.sub(r"\s+", " ", content.strip().lower())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    async def collect_from_feeds(
        self,
        feed_urls: list[str],
        min_length: int = 300,
        max_length: int = 3000,
    ) -> list[dict]:
        """여러 피드에서 수집 및 필터링.

        Args:
            feed_urls: RSS 피드 URL 목록
            min_length: 최소 글자 수
            max_length: 최대 글자 수

        Returns:
            수집된 글 목록 (중복 제거됨)
        """
        all_items = []
        seen_hashes = set()

        for url in feed_urls:
            items = await self.fetch_feed(url)

            # 길이 필터
            items = self.filter_by_length(items, min_length, max_length)

            # 키워드 필터
            items = self.filter_by_keywords(items)

            # 중복 제거
            for item in items:
                content_hash = self.compute_content_hash(item["content"])
                if content_hash not in seen_hashes:
                    seen_hashes.add(content_hash)
                    item["content_hash"] = content_hash
                    all_items.append(item)

        logger.info(f"총 {len(all_items)}건 수집 (중복 제거 후)")
        return all_items

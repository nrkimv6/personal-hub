"""Search Collector - 검색 API 기반 글 수집."""

import hashlib
import re
from typing import Optional

import httpx

from app.core.config import settings


class NaverSearchCollector:
    """네이버 검색 API 수집기."""

    BASE_URL = "https://openapi.naver.com/v1/search"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
        self.client_id = client_id or settings.NAVER_CLIENT_ID
        self.client_secret = client_secret or settings.NAVER_CLIENT_SECRET
        self.headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
        }

    def is_configured(self) -> bool:
        """API 키가 설정되었는지 확인."""
        return bool(self.client_id and self.client_secret)

    async def search_blog(
        self,
        query: str,
        display: int = 100,
        start: int = 1,
        sort: str = "date",
    ) -> list[dict]:
        """블로그 검색.

        Args:
            query: 검색어
            display: 결과 수 (1-100)
            start: 시작 위치 (1-1000)
            sort: 정렬 방식 (sim: 유사도, date: 날짜)

        Returns:
            검색 결과 리스트
        """
        if not self.is_configured():
            return []

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    f"{self.BASE_URL}/blog.json",
                    params={
                        "query": query,
                        "display": min(display, 100),
                        "start": start,
                        "sort": sort,
                    },
                    headers=self.headers,
                )
                resp.raise_for_status()
                data = resp.json()
                return self._parse_items(data.get("items", []), "naver_blog")
            except Exception:
                return []

    async def search_cafe(
        self,
        query: str,
        display: int = 100,
        start: int = 1,
        sort: str = "date",
    ) -> list[dict]:
        """카페 검색.

        Args:
            query: 검색어
            display: 결과 수 (1-100)
            start: 시작 위치 (1-1000)
            sort: 정렬 방식 (sim: 유사도, date: 날짜)

        Returns:
            검색 결과 리스트
        """
        if not self.is_configured():
            return []

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    f"{self.BASE_URL}/cafearticle.json",
                    params={
                        "query": query,
                        "display": min(display, 100),
                        "start": start,
                        "sort": sort,
                    },
                    headers=self.headers,
                )
                resp.raise_for_status()
                data = resp.json()
                return self._parse_items(data.get("items", []), "naver_cafe")
            except Exception:
                return []

    def _parse_items(self, items: list[dict], source: str) -> list[dict]:
        """검색 결과 파싱."""
        results = []
        for item in items:
            title = self._strip_html(item.get("title", ""))
            description = self._strip_html(item.get("description", ""))
            link = item.get("link", "")

            # 제목 + 설명을 합쳐서 content로 사용
            content = f"{title}\n\n{description}" if description else title

            if len(content) >= 50:  # 최소 길이
                results.append({
                    "title": title,
                    "content": content,
                    "link": link,
                    "source": source,
                    "published": item.get("postdate"),
                    "author": item.get("bloggername") or item.get("cafename"),
                    "content_hash": self._compute_hash(content),
                })
        return results

    @staticmethod
    def _strip_html(text: str) -> str:
        """HTML 태그 제거."""
        if not text:
            return ""
        # HTML 엔티티 변환
        text = text.replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&amp;", "&").replace("&quot;", '"')
        text = text.replace("&nbsp;", " ")
        # 태그 제거
        return re.sub(r"<[^>]+>", "", text).strip()

    @staticmethod
    def _compute_hash(content: str) -> str:
        """콘텐츠 해시 계산."""
        return hashlib.sha256(content.encode()).hexdigest()


class KakaoSearchCollector:
    """카카오 검색 API 수집기."""

    BASE_URL = "https://dapi.kakao.com/v2/search"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.KAKAO_REST_API_KEY
        self.headers = {"Authorization": f"KakaoAK {self.api_key}"}

    def is_configured(self) -> bool:
        """API 키가 설정되었는지 확인."""
        return bool(self.api_key)

    async def search_blog(
        self,
        query: str,
        size: int = 50,
        page: int = 1,
        sort: str = "recency",
    ) -> list[dict]:
        """블로그 검색.

        Args:
            query: 검색어
            size: 결과 수 (1-50)
            page: 페이지 (1-50)
            sort: 정렬 방식 (accuracy: 정확도, recency: 최신순)

        Returns:
            검색 결과 리스트
        """
        if not self.is_configured():
            return []

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    f"{self.BASE_URL}/blog",
                    params={
                        "query": query,
                        "size": min(size, 50),
                        "page": page,
                        "sort": sort,
                    },
                    headers=self.headers,
                )
                resp.raise_for_status()
                data = resp.json()
                return self._parse_documents(data.get("documents", []), "kakao_blog")
            except Exception:
                return []

    async def search_cafe(
        self,
        query: str,
        size: int = 50,
        page: int = 1,
        sort: str = "recency",
    ) -> list[dict]:
        """카페 검색.

        Args:
            query: 검색어
            size: 결과 수 (1-50)
            page: 페이지 (1-50)
            sort: 정렬 방식 (accuracy: 정확도, recency: 최신순)

        Returns:
            검색 결과 리스트
        """
        if not self.is_configured():
            return []

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    f"{self.BASE_URL}/cafe",
                    params={
                        "query": query,
                        "size": min(size, 50),
                        "page": page,
                        "sort": sort,
                    },
                    headers=self.headers,
                )
                resp.raise_for_status()
                data = resp.json()
                return self._parse_documents(data.get("documents", []), "kakao_cafe")
            except Exception:
                return []

    def _parse_documents(self, docs: list[dict], source: str) -> list[dict]:
        """검색 결과 파싱."""
        results = []
        for doc in docs:
            title = self._strip_html(doc.get("title", ""))
            contents = self._strip_html(doc.get("contents", ""))

            # 제목 + 내용 합치기
            content = f"{title}\n\n{contents}" if contents else title

            if len(content) >= 50:  # 최소 길이
                results.append({
                    "title": title,
                    "content": content,
                    "link": doc.get("url"),
                    "source": source,
                    "published": doc.get("datetime"),
                    "author": doc.get("blogname") or doc.get("cafename"),
                    "content_hash": self._compute_hash(content),
                })
        return results

    @staticmethod
    def _strip_html(text: str) -> str:
        """HTML 태그 제거."""
        if not text:
            return ""
        return re.sub(r"<[^>]+>", "", text).strip()

    @staticmethod
    def _compute_hash(content: str) -> str:
        """콘텐츠 해시 계산."""
        return hashlib.sha256(content.encode()).hexdigest()


class SearchContentFilter:
    """검색 결과 필터링."""

    # 시니어 타겟 선호 키워드
    PREFER_KEYWORDS = [
        "에세이", "수필", "일상", "가족", "부모", "자녀", "손주",
        "추억", "회상", "감사", "건강", "산책", "정원", "텃밭",
        "계절", "봄", "여름", "가을", "겨울", "고향", "옛날",
        "부부", "은퇴", "노후", "여행", "취미", "독서",
    ]

    # 제외 키워드 (젊은 세대 콘텐츠)
    EXCLUDE_KEYWORDS = [
        "취준", "대학생", "20대", "MZ", "틱톡", "릴스",
        "인스타", "클럽", "술자리", "야근", "회사원",
        "면접", "자소서", "스펙", "토익", "취업",
    ]

    @classmethod
    def filter_items(
        cls,
        items: list[dict],
        min_length: int = 100,
        max_length: int = 5000,
    ) -> list[dict]:
        """검색 결과 필터링.

        Args:
            items: 검색 결과 리스트
            min_length: 최소 길이
            max_length: 최대 길이

        Returns:
            필터링된 결과 리스트
        """
        filtered = []

        # 키워드 소문자 변환 (한 번만)
        exclude_lower = [kw.lower() for kw in cls.EXCLUDE_KEYWORDS]
        prefer_lower = [kw.lower() for kw in cls.PREFER_KEYWORDS]

        for item in items:
            content = item.get("content", "")
            content_lower = content.lower()

            # 길이 체크
            if len(content) < min_length or len(content) > max_length:
                continue

            # 제외 키워드 체크
            if any(kw in content_lower for kw in exclude_lower):
                continue

            # 선호 키워드 점수 계산
            score = sum(1 for kw in prefer_lower if kw in content_lower)
            item["relevance_score"] = score

            filtered.append(item)

        # 점수순 정렬
        return sorted(filtered, key=lambda x: x.get("relevance_score", 0), reverse=True)

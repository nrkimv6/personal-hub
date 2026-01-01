"""Public Data Collector - 공개 데이터 수집기."""

import hashlib
from typing import Optional

import httpx


class WikisourceCollector:
    """위키문헌 수집기.

    한국어 위키문헌에서 저작권 만료 수필/에세이를 수집합니다.
    API 키 불필요.
    """

    BASE_URL = "https://ko.wikisource.org/w/api.php"

    # 시니어 타겟 카테고리
    DEFAULT_CATEGORIES = [
        "대한민국의_수필",
        "한국의_수필",
        "수필",
    ]

    async def list_category_pages(
        self,
        category: str,
        limit: int = 100,
    ) -> list[dict]:
        """카테고리 내 문서 목록 조회.

        Args:
            category: 카테고리 이름 (분류: 제외)
            limit: 최대 결과 수

        Returns:
            문서 목록 [{title, pageid}, ...]
        """
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"분류:{category}",
            "cmlimit": min(limit, 500),
            "cmtype": "page",  # 페이지만 (하위 카테고리 제외)
            "format": "json",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(self.BASE_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
                return data.get("query", {}).get("categorymembers", [])
            except Exception:
                return []

    async def get_page_content(self, title: str) -> Optional[str]:
        """문서 본문 가져오기.

        Args:
            title: 문서 제목

        Returns:
            본문 텍스트 또는 None
        """
        params = {
            "action": "query",
            "titles": title,
            "prop": "extracts",
            "explaintext": True,
            "format": "json",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(self.BASE_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
                pages = data.get("query", {}).get("pages", {})
                for page in pages.values():
                    return page.get("extract")
            except Exception:
                pass
        return None

    async def collect_category(
        self,
        category: str,
        min_length: int = 200,
        max_length: int = 10000,
    ) -> list[dict]:
        """카테고리 내 문서 수집.

        Args:
            category: 카테고리 이름
            min_length: 최소 글자 수
            max_length: 최대 글자 수

        Returns:
            수집된 문서 리스트
        """
        pages = await self.list_category_pages(category)
        results = []

        for page in pages:
            title = page.get("title", "")
            content = await self.get_page_content(title)

            if not content:
                continue

            # 길이 필터
            if len(content) < min_length or len(content) > max_length:
                continue

            results.append({
                "title": title,
                "content": content,
                "link": f"https://ko.wikisource.org/wiki/{title.replace(' ', '_')}",
                "source": "wikisource",
                "author": None,  # 작가 정보는 별도 파싱 필요
                "content_hash": self._compute_hash(content),
            })

        return results

    async def collect_all_categories(
        self,
        categories: Optional[list[str]] = None,
        min_length: int = 200,
        max_length: int = 10000,
    ) -> list[dict]:
        """여러 카테고리에서 수집.

        Args:
            categories: 카테고리 목록 (None이면 기본 카테고리)
            min_length: 최소 글자 수
            max_length: 최대 글자 수

        Returns:
            수집된 문서 리스트
        """
        if categories is None:
            categories = self.DEFAULT_CATEGORIES

        all_results = []
        seen_hashes = set()

        for category in categories:
            items = await self.collect_category(
                category,
                min_length=min_length,
                max_length=max_length,
            )

            # 중복 제거
            for item in items:
                if item["content_hash"] not in seen_hashes:
                    seen_hashes.add(item["content_hash"])
                    all_results.append(item)

        return all_results

    @staticmethod
    def _compute_hash(content: str) -> str:
        """콘텐츠 해시 계산."""
        return hashlib.sha256(content.encode()).hexdigest()


class PublicDataCollector:
    """공공데이터포털 수집기.

    공공데이터포털(data.go.kr) API를 사용합니다.
    API 키가 필요합니다.
    """

    def __init__(self, service_key: str = ""):
        self.service_key = service_key
        self.datasets: list[dict] = []

    def is_configured(self) -> bool:
        """API 키 설정 여부."""
        return bool(self.service_key)

    def register_dataset(
        self,
        name: str,
        endpoint: str,
        content_field: str,
        title_field: Optional[str] = None,
    ) -> None:
        """데이터셋 등록.

        Args:
            name: 데이터셋 이름
            endpoint: API 엔드포인트
            content_field: 본문 필드명
            title_field: 제목 필드명 (선택)
        """
        self.datasets.append({
            "name": name,
            "endpoint": endpoint,
            "content_field": content_field,
            "title_field": title_field,
        })

    async def collect_dataset(
        self,
        endpoint: str,
        content_field: str,
        title_field: Optional[str] = None,
        page: int = 1,
        num_rows: int = 100,
    ) -> list[dict]:
        """데이터셋 수집.

        Args:
            endpoint: API 엔드포인트
            content_field: 본문 필드명
            title_field: 제목 필드명
            page: 페이지 번호
            num_rows: 페이지당 행 수

        Returns:
            수집된 항목 리스트
        """
        if not self.is_configured():
            return []

        params = {
            "serviceKey": self.service_key,
            "pageNo": page,
            "numOfRows": num_rows,
            "type": "json",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(endpoint, params=params)
                resp.raise_for_status()
                data = resp.json()

                # 공공데이터 응답 구조는 데이터셋마다 다름
                # 일반적인 구조: response > body > items > item
                items = self._extract_items(data)
                results = []

                for item in items:
                    content = item.get(content_field, "")
                    if content and len(str(content)) >= 100:
                        results.append({
                            "title": item.get(title_field, "") if title_field else "",
                            "content": str(content),
                            "source": "data_go_kr",
                            "link": endpoint,
                            "content_hash": self._compute_hash(str(content)),
                        })

                return results

            except Exception:
                return []

    def _extract_items(self, data: dict) -> list[dict]:
        """응답에서 항목 추출.

        다양한 공공데이터 응답 구조 처리.
        """
        # 구조 1: response > body > items > item
        if "response" in data:
            body = data["response"].get("body", {})
            items = body.get("items", {})
            if isinstance(items, dict):
                return items.get("item", [])
            return items if isinstance(items, list) else []

        # 구조 2: data > list
        if "data" in data:
            return data["data"] if isinstance(data["data"], list) else []

        # 구조 3: 직접 리스트
        if isinstance(data, list):
            return data

        return []

    async def collect_all(self) -> list[dict]:
        """등록된 모든 데이터셋 수집."""
        all_results = []

        for ds in self.datasets:
            items = await self.collect_dataset(
                endpoint=ds["endpoint"],
                content_field=ds["content_field"],
                title_field=ds.get("title_field"),
            )
            all_results.extend(items)

        return all_results

    @staticmethod
    def _compute_hash(content: str) -> str:
        """콘텐츠 해시 계산."""
        return hashlib.sha256(content.encode()).hexdigest()

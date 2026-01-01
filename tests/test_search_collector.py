"""Search Collector 테스트."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.modules.writing.services.search_collector import (
    NaverSearchCollector,
    KakaoSearchCollector,
    SearchContentFilter,
)


# ========== NaverSearchCollector 테스트 ==========


class TestNaverSearchCollector:
    """네이버 검색 수집기 테스트."""

    def test_is_configured_without_keys(self):
        """API 키 없이 설정 확인."""
        collector = NaverSearchCollector(client_id="", client_secret="")
        assert collector.is_configured() is False

    def test_is_configured_with_keys(self):
        """API 키 있을 때 설정 확인."""
        collector = NaverSearchCollector(
            client_id="test_id",
            client_secret="test_secret",
        )
        assert collector.is_configured() is True

    def test_strip_html(self):
        """HTML 태그 제거 테스트."""
        text = "<b>강조</b> 일반 <a href='#'>링크</a>"
        result = NaverSearchCollector._strip_html(text)
        assert result == "강조 일반 링크"

    def test_strip_html_entities(self):
        """HTML 엔티티 변환 테스트."""
        text = "&amp; &quot;quote&quot; &nbsp;space"
        result = NaverSearchCollector._strip_html(text)
        assert "&" in result
        assert '"quote"' in result

    def test_compute_hash(self):
        """해시 계산 테스트."""
        content = "테스트 콘텐츠"
        hash1 = NaverSearchCollector._compute_hash(content)
        hash2 = NaverSearchCollector._compute_hash(content)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256

    def test_parse_items(self):
        """검색 결과 파싱 테스트."""
        collector = NaverSearchCollector(client_id="", client_secret="")
        # content는 50자 이상이어야 함 (title + description)
        items = [
            {
                "title": "<b>테스트</b> 제목 - 충분히 긴 제목입니다",
                "description": "이것은 테스트 설명입니다. 충분히 긴 내용이어야 합니다. 시니어를 위한 따뜻한 에세이입니다.",
                "link": "https://example.com/post1",
                "bloggername": "테스터",
                "postdate": "20260101",
            }
        ]
        result = collector._parse_items(items, "naver_blog")

        assert len(result) == 1
        assert "테스트 제목" in result[0]["title"]
        assert "테스트 설명" in result[0]["content"]
        assert result[0]["source"] == "naver_blog"
        assert result[0]["author"] == "테스터"
        assert "content_hash" in result[0]

    def test_parse_items_filters_short_content(self):
        """짧은 콘텐츠 필터링 테스트."""
        collector = NaverSearchCollector(client_id="", client_secret="")
        items = [
            {
                "title": "짧은",
                "description": "글",
                "link": "https://example.com/short",
            }
        ]
        result = collector._parse_items(items, "naver_blog")
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_search_blog_without_config(self):
        """설정 없이 검색 시 빈 결과."""
        collector = NaverSearchCollector(client_id="", client_secret="")
        result = await collector.search_blog("테스트")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_blog_with_mock(self):
        """블로그 검색 모킹 테스트."""
        collector = NaverSearchCollector(
            client_id="test_id",
            client_secret="test_secret",
        )

        mock_response = {
            "items": [
                {
                    "title": "에세이 제목 - 시니어를 위한 따뜻한 글",
                    "description": "이것은 에세이 내용입니다. 시니어를 위한 따뜻한 글입니다. 가족과 함께하는 시간.",
                    "link": "https://blog.naver.com/test/123",
                    "bloggername": "에세이스트",
                    "postdate": "20260101",
                }
            ]
        }

        with patch(
            "app.modules.writing.services.search_collector.httpx.AsyncClient"
        ) as mock_client:
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response_obj)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await collector.search_blog("에세이")

            assert len(result) == 1
            assert "에세이 제목" in result[0]["title"]

    @pytest.mark.asyncio
    async def test_search_cafe_with_mock(self):
        """카페 검색 모킹 테스트."""
        collector = NaverSearchCollector(
            client_id="test_id",
            client_secret="test_secret",
        )

        mock_response = {
            "items": [
                {
                    "title": "카페 글 제목 - 에세이 모음",
                    "description": "카페에서 작성된 에세이입니다. 부모님 이야기를 담은 따뜻한 글.",
                    "link": "https://cafe.naver.com/test/123",
                    "cafename": "에세이 카페",
                    "postdate": "20260101",
                }
            ]
        }

        with patch(
            "app.modules.writing.services.search_collector.httpx.AsyncClient"
        ) as mock_client:
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response_obj)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await collector.search_cafe("에세이")

            assert len(result) == 1
            assert result[0]["source"] == "naver_cafe"


# ========== KakaoSearchCollector 테스트 ==========


class TestKakaoSearchCollector:
    """카카오 검색 수집기 테스트."""

    def test_is_configured_without_key(self):
        """API 키 없이 설정 확인."""
        collector = KakaoSearchCollector(api_key="")
        assert collector.is_configured() is False

    def test_is_configured_with_key(self):
        """API 키 있을 때 설정 확인."""
        collector = KakaoSearchCollector(api_key="test_key")
        assert collector.is_configured() is True

    def test_parse_documents(self):
        """검색 결과 파싱 테스트."""
        collector = KakaoSearchCollector(api_key="test")
        # content는 50자 이상이어야 함 (title + contents)
        docs = [
            {
                "title": "<b>다음</b> 블로그 제목 - 따뜻한 에세이",
                "contents": "다음 블로그 내용입니다. 따뜻한 에세이. 시니어를 위한 글입니다.",
                "url": "https://blog.daum.net/test/123",
                "blogname": "다음 블로거",
                "datetime": "2026-01-01T12:00:00",
            }
        ]
        result = collector._parse_documents(docs, "kakao_blog")

        assert len(result) == 1
        assert "다음 블로그 제목" in result[0]["title"]
        assert result[0]["source"] == "kakao_blog"

    @pytest.mark.asyncio
    async def test_search_blog_without_config(self):
        """설정 없이 검색 시 빈 결과."""
        collector = KakaoSearchCollector(api_key="")
        result = await collector.search_blog("테스트")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_blog_with_mock(self):
        """블로그 검색 모킹 테스트."""
        collector = KakaoSearchCollector(api_key="test_key")

        mock_response = {
            "documents": [
                {
                    "title": "카카오 에세이 - 따뜻한 이야기",
                    "contents": "카카오 블로그의 에세이입니다. 시니어 독자를 위한 글. 가족 이야기.",
                    "url": "https://blog.daum.net/test/456",
                    "blogname": "에세이스트",
                    "datetime": "2026-01-01T12:00:00",
                }
            ]
        }

        with patch(
            "app.modules.writing.services.search_collector.httpx.AsyncClient"
        ) as mock_client:
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response_obj)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await collector.search_blog("에세이")

            assert len(result) == 1
            assert "카카오 에세이" in result[0]["title"]


# ========== SearchContentFilter 테스트 ==========


class TestSearchContentFilter:
    """콘텐츠 필터 테스트."""

    def test_filter_by_length(self):
        """길이 필터링 테스트."""
        items = [
            {"content": "a" * 50},   # 너무 짧음
            {"content": "a" * 200},  # OK
            {"content": "a" * 6000}, # 너무 김
        ]
        result = SearchContentFilter.filter_items(items, min_length=100, max_length=5000)
        assert len(result) == 1

    def test_filter_excludes_young_content(self):
        """젊은 세대 콘텐츠 제외 테스트."""
        items = [
            {"content": "이것은 취준생을 위한 글입니다. " + "a" * 200},
            {"content": "대학생 시절 이야기입니다. " + "a" * 200},
            {"content": "MZ세대 트렌드입니다. " + "a" * 200},
        ]
        result = SearchContentFilter.filter_items(items, min_length=100, max_length=5000)
        assert len(result) == 0

    def test_filter_calculates_relevance_score(self):
        """관련성 점수 계산 테스트."""
        items = [
            {"content": "부모님과 가족 이야기입니다. 추억을 회상합니다. " + "a" * 200},
            {"content": "일반적인 이야기입니다. " + "a" * 200},
        ]
        result = SearchContentFilter.filter_items(items, min_length=100, max_length=5000)

        assert len(result) == 2
        # 첫 번째가 더 높은 점수여야 함 (관련 키워드 많음)
        assert result[0]["relevance_score"] > result[1]["relevance_score"]

    def test_filter_sorts_by_relevance(self):
        """관련성 점수순 정렬 테스트."""
        items = [
            {"content": "일반적인 이야기입니다. " + "a" * 200},  # 0점
            {"content": "에세이와 추억 이야기입니다. " + "a" * 200},  # 2점
            {"content": "가족 부모 자녀 이야기입니다. " + "a" * 200},  # 3점
        ]
        result = SearchContentFilter.filter_items(items, min_length=100, max_length=5000)

        assert len(result) == 3
        # 점수 높은 순으로 정렬되어야 함
        assert result[0]["relevance_score"] >= result[1]["relevance_score"]
        assert result[1]["relevance_score"] >= result[2]["relevance_score"]

    def test_prefer_keywords_list(self):
        """선호 키워드 리스트 확인."""
        assert "에세이" in SearchContentFilter.PREFER_KEYWORDS
        assert "가족" in SearchContentFilter.PREFER_KEYWORDS
        assert "추억" in SearchContentFilter.PREFER_KEYWORDS

    def test_exclude_keywords_list(self):
        """제외 키워드 리스트 확인."""
        assert "취준" in SearchContentFilter.EXCLUDE_KEYWORDS
        assert "대학생" in SearchContentFilter.EXCLUDE_KEYWORDS
        assert "MZ" in SearchContentFilter.EXCLUDE_KEYWORDS

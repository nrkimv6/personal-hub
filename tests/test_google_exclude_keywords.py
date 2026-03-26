"""
Google 검색 제외 키워드 기능 단위 테스트 (RIGHT-BICEP)
"""
import pytest
from unittest.mock import MagicMock


# === _build_url 테스트 ===

class TestBuildUrlExcludeKeywords:
    """_build_url()의 exclude_keywords 처리 테스트."""

    def _get_crawler(self):
        """테스트용 GoogleSearchCrawler 인스턴스 생성."""
        from app.modules.google_search.services.crawler import GoogleSearchCrawler
        page = MagicMock()
        db = MagicMock()
        return GoogleSearchCrawler(page, db)

    def test_build_url_with_exclude_keywords_right(self):
        """Right: exclude_keywords가 있으면 URL 쿼리에 - 연산자로 포함."""
        from urllib.parse import unquote
        crawler = self._get_crawler()
        url = crawler._build_url(
            query="선착순 이벤트",
            search_params={"exclude_keywords": ["구매", "판매"]}
        )
        decoded = unquote(url)
        assert "-구매" in decoded
        assert "-판매" in decoded

    def test_build_url_without_exclude_keywords_right(self):
        """Right: exclude_keywords 없으면 기존 URL과 동일하게 동작."""
        crawler = self._get_crawler()
        url_without = crawler._build_url(query="이벤트", search_params={"lr": "lang_ko"})
        url_with_empty = crawler._build_url(query="이벤트", search_params={"lr": "lang_ko", "exclude_keywords": []})
        # 쿼리 부분만 비교 (exclude_keywords가 URL 파라미터에 추가되지 않아야 함)
        assert "exclude_keywords" not in url_without
        assert "exclude_keywords" not in url_with_empty

    def test_build_url_exclude_keywords_boundary(self):
        """Boundary: 빈 문자열 키워드 스킵, 유효 키워드만 반영."""
        from urllib.parse import unquote
        crawler = self._get_crawler()
        url = crawler._build_url(
            query="이벤트",
            search_params={"exclude_keywords": ["", "구매", "  "]}
        )
        decoded = unquote(url)
        assert "-구매" in decoded
        # 빈 문자열은 포함되지 않아야 함
        assert "- " not in decoded

    def test_build_url_exclude_keywords_special_chars_boundary(self):
        """Boundary: 특수문자 키워드 처리."""
        from urllib.parse import unquote
        crawler = self._get_crawler()
        url = crawler._build_url(
            query="이벤트",
            search_params={"exclude_keywords": ["C++"]}
        )
        decoded = unquote(url)
        assert "-C++" in decoded


# === SearchParams 스키마 테스트 ===

class TestSearchParamsSchema:
    """SearchParams 스키마의 exclude_keywords 필드 테스트."""

    def test_search_params_schema_exclude_keywords_right(self):
        """Right: exclude_keywords 필드가 model_dump에 포함됨."""
        from app.modules.google_search.models.schemas import SearchParams
        params = SearchParams(exclude_keywords=["구매"])
        dumped = params.model_dump()
        assert "exclude_keywords" in dumped
        assert dumped["exclude_keywords"] == ["구매"]

    def test_search_params_schema_exclude_keywords_optional(self):
        """Right: exclude_keywords가 없으면 None."""
        from app.modules.google_search.models.schemas import SearchParams
        params = SearchParams(lr="lang_ko")
        assert params.exclude_keywords is None


# === _should_exclude 테스트 ===

class TestShouldExclude:
    """GoogleSearchWorker._should_exclude() 테스트."""

    def _get_worker(self):
        from app.worker.google_search_worker import GoogleSearchWorker
        worker = GoogleSearchWorker.__new__(GoogleSearchWorker)
        worker.name = "test"
        return worker

    def _make_result(self, title="", snippet=""):
        result = MagicMock()
        result.title = title
        result.snippet = snippet
        return result

    def test_should_exclude_right(self):
        """Right: 제외 키워드가 title에 포함되면 True."""
        worker = self._get_worker()
        result = self._make_result(title="구매 이벤트", snippet="할인 정보")
        assert worker._should_exclude(result, ["구매"]) is True

    def test_should_exclude_snippet_right(self):
        """Right: 제외 키워드가 snippet에 포함되면 True."""
        worker = self._get_worker()
        result = self._make_result(title="이벤트", snippet="구매 링크 포함")
        assert worker._should_exclude(result, ["구매"]) is True

    def test_should_exclude_boundary_case_insensitive(self):
        """Boundary: 영문 대소문자 무시."""
        worker = self._get_worker()
        result = self._make_result(title="Sale Event", snippet="")
        assert worker._should_exclude(result, ["sale"]) is True
        assert worker._should_exclude(result, ["SALE"]) is True

    def test_should_exclude_boundary_partial_match(self):
        """Boundary: 부분 매칭 - '구매' in '선물구매하기' → True."""
        worker = self._get_worker()
        result = self._make_result(title="선물구매하기", snippet="")
        assert worker._should_exclude(result, ["구매"]) is True

    def test_should_exclude_error_none_keywords(self):
        """Error: exclude_keywords=None → False."""
        worker = self._get_worker()
        result = self._make_result(title="구매 이벤트", snippet="")
        assert worker._should_exclude(result, None) is False

    def test_should_exclude_error_empty_list(self):
        """Error: exclude_keywords=[] → False."""
        worker = self._get_worker()
        result = self._make_result(title="구매 이벤트", snippet="")
        assert worker._should_exclude(result, []) is False

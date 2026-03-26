"""
Google 검색 제외 키워드 통합 테스트
"""
import json
import pytest
from unittest.mock import MagicMock


class TestBuildUrlExcludeKeywordsIntegration:
    """실제 GoogleSearchCrawler 인스턴스를 사용한 통합 테스트."""

    def test_build_url_exclude_keywords_integration(self):
        """실제 인스턴스: exclude_keywords + as_sitesearch 함께 적용."""
        from urllib.parse import unquote
        from app.modules.google_search.services.crawler import GoogleSearchCrawler

        page = MagicMock()
        db = MagicMock()
        crawler = GoogleSearchCrawler(page, db)

        url = crawler._build_url(
            query="선착순 이벤트",
            search_params={"exclude_keywords": ["구매"], "as_sitesearch": "instagram.com"}
        )
        decoded = unquote(url)

        assert "site:instagram.com" in decoded
        assert "-구매" in decoded
        # as_sitesearch는 URL 파라미터로 추가되지 않아야 함
        assert "as_sitesearch" not in url
        # exclude_keywords는 URL 파라미터로 추가되지 않아야 함
        assert "exclude_keywords" not in url


class TestSearchParamsJsonRoundtrip:
    """SQLite 실물을 사용한 JSON 라운드트립 테스트."""

    def test_search_params_json_roundtrip(self):
        """search_params JSON에 exclude_keywords가 저장/복원됨."""
        import sqlite3
        import tempfile
        import os

        # 임시 DB 생성
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE google_saved_searches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    query TEXT NOT NULL,
                    search_params TEXT
                )
            """)
            search_params = json.dumps({"exclude_keywords": ["구매", "판매"]})
            conn.execute(
                "INSERT INTO google_saved_searches (name, query, search_params) VALUES (?, ?, ?)",
                ("테스트", "선착순 이벤트", search_params)
            )
            conn.commit()

            row = conn.execute("SELECT search_params FROM google_saved_searches WHERE name='테스트'").fetchone()
            result = json.loads(row[0])
            assert result["exclude_keywords"] == ["구매", "판매"]
            conn.close()
        finally:
            os.unlink(db_path)

"""
Google 검색 제외 키워드 E2E 테스트 (T4).

검증 범위:
- exclude_keywords 포함 SavedSearch 생성 → DB 저장
- 조회 시 exclude_keywords 반환
- 수정 시 exclude_keywords 갱신
- _build_url()이 exclude_keywords를 - 연산자로 변환

raw SQL fixture + 단위 검증 방식 사용:
  이유: 프로젝트의 UUID 컬럼이 SQLite in-memory에서 create_all 불가
  (test_google_search_site_restriction_http.py 동일 패턴)
"""
import json
import pytest
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


_CREATE_TABLES_SQL = """
PRAGMA foreign_keys=OFF;

CREATE TABLE IF NOT EXISTS google_saved_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(200) NOT NULL,
    query VARCHAR(500) NOT NULL,
    date_filter VARCHAR(10),
    max_pages INTEGER DEFAULT 1,
    search_params TEXT,
    service_account_id INTEGER,
    is_favorite INTEGER DEFAULT 0,
    notify_on_new INTEGER DEFAULT 0,
    last_search_id VARCHAR(36),
    last_run_at DATETIME,
    last_result_count INTEGER,
    enabled INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


@pytest.fixture
def db_session():
    import sqlite3
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(_CREATE_TABLES_SQL)
    conn.commit()

    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        creator=lambda: conn,
    )
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    conn.close()


class TestSavedSearchCrudWithExcludeKeywords:
    """exclude_keywords 포함 SavedSearch CRUD 검증."""

    def test_create_saved_search_with_exclude_keywords(self, db_session):
        """(1) SavedSearch 생성 + (2) 조회 → exclude_keywords 포함 확인."""
        from app.models.google_search import GoogleSavedSearch

        saved = GoogleSavedSearch(
            name="선착순 이벤트 검색",
            query="선착순 이벤트",
            max_pages=1,
            search_params=json.dumps({"exclude_keywords": ["구매"]}),
        )
        db_session.add(saved)
        db_session.commit()
        db_session.refresh(saved)

        stored = json.loads(saved.search_params)
        assert stored.get("exclude_keywords") == ["구매"]

    def test_update_saved_search_exclude_keywords(self, db_session):
        """(3) 수정 + (4) 재조회 → 변경 반영 검증."""
        from app.models.google_search import GoogleSavedSearch

        saved = GoogleSavedSearch(
            name="선착순 이벤트 검색",
            query="선착순 이벤트",
            max_pages=1,
            search_params=json.dumps({"exclude_keywords": ["구매"]}),
        )
        db_session.add(saved)
        db_session.commit()

        saved.search_params = json.dumps({"exclude_keywords": ["판매"]})
        db_session.commit()
        db_session.refresh(saved)

        updated = json.loads(saved.search_params)
        assert updated.get("exclude_keywords") == ["판매"]

    def test_build_url_with_exclude_keywords_applied(self):
        """_build_url()이 exclude_keywords를 - 연산자로 URL에 반영."""
        from urllib.parse import unquote
        from app.modules.google_search.services.crawler import GoogleSearchCrawler

        crawler = GoogleSearchCrawler(MagicMock(), MagicMock())
        url = crawler._build_url(
            query="선착순 이벤트",
            search_params={"exclude_keywords": ["구매"], "lr": "lang_ko"},
        )
        decoded = unquote(url)
        assert "-구매" in decoded
        # exclude_keywords는 URL 파라미터로 추가되지 않아야 함
        assert "exclude_keywords" not in url
        # lr은 URL 파라미터로 추가되어야 함
        assert "lr=" in url

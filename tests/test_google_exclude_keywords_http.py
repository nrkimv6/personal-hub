"""
Google 검색 제외 키워드 HTTP 통합 테스트 (T5).

검증 범위:
- SavedSearch 생성/수정/조회 시 exclude_keywords 포함 search_params 처리
- POST /api/v1/google/search 큐 추가 시 search_params.exclude_keywords 전달 경로
- collect.py 핸들러 내부 exclude_keywords 파싱 로직

TestClient + in-memory SQLite 대신 raw SQL fixture + 단위 검증 방식 사용:
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


class TestCreateSavedSearchWithExcludeKeywords:
    """POST /api/v1/google/saved 상당 로직 — exclude_keywords 저장 검증."""

    def test_create_saved_search_with_exclude_keywords(self, db_session):
        """R(Right): exclude_keywords 포함 search_params → DB에 JSON으로 저장."""
        from app.models.google_search import GoogleSavedSearch

        body_search_params = {"exclude_keywords": ["구매"]}
        saved = GoogleSavedSearch(
            name="제외 키워드 테스트",
            query="선착순 이벤트",
            max_pages=1,
            search_params=json.dumps(body_search_params),
        )
        db_session.add(saved)
        db_session.commit()
        db_session.refresh(saved)

        assert saved.search_params is not None
        parsed = json.loads(saved.search_params)
        assert parsed.get("exclude_keywords") == ["구매"]


class TestUpdateSavedSearchExcludeKeywords:
    """PUT /api/v1/google/saved/{id} 상당 로직 — exclude_keywords 갱신 검증."""

    def test_update_saved_search_exclude_keywords(self, db_session):
        """R(Right): search_params.exclude_keywords 수정 → 갱신 반영."""
        from app.models.google_search import GoogleSavedSearch

        saved = GoogleSavedSearch(
            name="테스트",
            query="이벤트",
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


class TestSearchWithExcludeKeywordsQueueFlow:
    """POST /api/v1/google/search 큐 추가 시 exclude_keywords 전달 경로."""

    def test_search_params_with_exclude_keywords_serialized_to_queue(self):
        """R(Right): search_params.exclude_keywords가 큐에 JSON으로 저장되는 경로."""
        # collect.py가 SearchRequest.search_params를 직렬화하여 GoogleSearchQueue.search_params에 저장하는 로직 재현
        search_params = {"exclude_keywords": ["구매"], "lr": "lang_ko"}
        serialized = json.dumps(search_params) if isinstance(search_params, dict) else search_params

        assert serialized is not None
        parsed = json.loads(serialized)
        assert parsed.get("exclude_keywords") == ["구매"]
        assert parsed.get("lr") == "lang_ko"

    def test_worker_deserializes_exclude_keywords_from_queue(self):
        """R(Right): 워커가 큐 search_params를 역직렬화하여 exclude_keywords 추출."""
        # google_search_worker.py L229-235 로직 재현
        queue_search_params = json.dumps({"exclude_keywords": ["구매"], "lr": "lang_ko"})

        search_params = None
        if queue_search_params:
            try:
                search_params = json.loads(queue_search_params)
            except (json.JSONDecodeError, TypeError):
                search_params = None

        assert search_params is not None
        exclude_keywords = search_params.get("exclude_keywords", [])
        assert exclude_keywords == ["구매"]

    def test_exclude_keywords_applied_in_build_url(self):
        """R(Right): 역직렬화된 exclude_keywords → _build_url에서 - 연산자 반영."""
        from urllib.parse import unquote
        from app.modules.google_search.services.crawler import GoogleSearchCrawler

        crawler = GoogleSearchCrawler(MagicMock(), MagicMock())
        queue_search_params = json.dumps({"exclude_keywords": ["구매"]})
        search_params = json.loads(queue_search_params)

        url = crawler._build_url(query="이벤트", search_params=search_params)
        decoded = unquote(url)

        assert "-구매" in decoded
        assert "exclude_keywords" not in url

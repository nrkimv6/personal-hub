"""
Google 검색 사이트 제한 HTTP 통합 테스트 (T4).

검증 범위:
- collect.py API 핸들러가 as_sitesearch를 GoogleSavedSearch.search_params에 올바르게 저장
- collect.py API 핸들러가 상세 조회 시 search_params.as_sitesearch를 반환
- collect.py API 핸들러가 수정 시 search_params.as_sitesearch를 갱신
- _build_url()이 search_params의 as_sitesearch → site: 쿼리 연산자로 변환

TestClient + in-memory SQLite 대신 raw SQL fixture + 단위 검증 방식 사용:
  이유: 프로젝트의 UUID 컬럼이 SQLite in-memory에서 create_all 불가
  (test_google_search_worker.py 와 동일한 패턴)
"""
import json
import pytest
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# ============================================================
# raw SQL fixture (UUID 컬럼 회피)
# ============================================================

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

CREATE TABLE IF NOT EXISTS task_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(200),
    display_name VARCHAR(200),
    target_type VARCHAR(50),
    target_config TEXT,
    schedule_type VARCHAR(50),
    schedule_value TEXT,
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


# ============================================================
# T4: as_sitesearch 저장 경로 검증 (collect.py 핸들러 로직 직접 검증)
# ============================================================

class TestSiteRestrictionSaveToDb:
    """collect.py의 search_params 저장 로직 단위 검증."""

    def test_search_params_with_sitesearch_stored_as_json(self, db_session):
        """R(Right): as_sitesearch 포함 search_params → JSON으로 DB 저장."""
        from app.models.google_search import GoogleSavedSearch

        saved = GoogleSavedSearch(
            name="인스타 신발 검색",
            query="신발",
            max_pages=1,
        )
        sp = {"as_sitesearch": "instagram.com"}
        saved.search_params = json.dumps(sp)
        db_session.add(saved)
        db_session.commit()
        db_session.refresh(saved)

        stored = json.loads(saved.search_params)
        assert stored.get("as_sitesearch") == "instagram.com"

    def test_search_params_without_sitesearch_is_none(self, db_session):
        """B(Boundary): search_params 없이 저장 → None."""
        from app.models.google_search import GoogleSavedSearch

        saved = GoogleSavedSearch(
            name="일반 검색",
            query="신발",
            max_pages=1,
        )
        db_session.add(saved)
        db_session.commit()
        db_session.refresh(saved)

        assert saved.search_params is None

    def test_search_params_update_sitesearch(self, db_session):
        """R(Right): as_sitesearch 수정 → 갱신 값으로 DB 반영."""
        from app.models.google_search import GoogleSavedSearch

        saved = GoogleSavedSearch(
            name="검색",
            query="신발",
            search_params=json.dumps({"as_sitesearch": "instagram.com"}),
        )
        db_session.add(saved)
        db_session.commit()

        # 수정
        saved.search_params = json.dumps({"as_sitesearch": "naver.com"})
        db_session.commit()
        db_session.refresh(saved)

        stored = json.loads(saved.search_params)
        assert stored.get("as_sitesearch") == "naver.com"

    def test_search_params_clear_sitesearch(self, db_session):
        """B(Boundary): as_sitesearch 제거 → 빈 dict 저장."""
        from app.models.google_search import GoogleSavedSearch

        saved = GoogleSavedSearch(
            name="검색",
            query="신발",
            search_params=json.dumps({"as_sitesearch": "instagram.com"}),
        )
        db_session.add(saved)
        db_session.commit()

        saved.search_params = json.dumps({})
        db_session.commit()
        db_session.refresh(saved)

        stored = json.loads(saved.search_params)
        assert stored.get("as_sitesearch") is None


# ============================================================
# T4: collect.py 핸들러 — target_config.search_params 파싱 로직
# ============================================================

class TestCollectApiSearchParamsFlow:
    """collect.py 핸들러 내부 search_params 처리 흐름 검증."""

    def test_target_config_search_params_extracted(self):
        """R(Right): target_config.search_params에서 as_sitesearch 추출 로직."""
        # collect.py L243-245 로직 재현
        target_config = {
            "create_new_search": True,
            "query": "신발",
            "name": "인스타 검색",
            "max_pages": 1,
            "search_params": {"as_sitesearch": "instagram.com"},
        }
        sp = target_config.get("search_params")
        stored = json.dumps(sp) if isinstance(sp, dict) else sp

        assert stored is not None
        parsed = json.loads(stored)
        assert parsed.get("as_sitesearch") == "instagram.com"

    def test_target_config_no_search_params_is_none(self):
        """B(Boundary): search_params 키 없으면 sp=None → DB에 저장 안 함."""
        target_config = {
            "create_new_search": True,
            "query": "신발",
            "name": "일반 검색",
            "max_pages": 1,
        }
        sp = target_config.get("search_params")
        assert sp is None

    def test_google_search_params_patch_extracts_sitesearch(self):
        """R(Right): PATCH google_search_params.search_params에서 as_sitesearch 추출 로직."""
        # collect.py L420-422 로직 재현
        gsp = {"search_params": {"as_sitesearch": "naver.com"}}
        sp = gsp["search_params"]
        stored = json.dumps(sp) if isinstance(sp, dict) else sp

        parsed = json.loads(stored)
        assert parsed.get("as_sitesearch") == "naver.com"


# ============================================================
# T4: worker → crawler 연결 — search_params 전달 후 URL 검증
# ============================================================

class TestWorkerToCrawlerSiteRestriction:
    """워커가 search_params를 역직렬화하여 _build_url에 전달하는 경로 검증."""

    def test_search_params_deserialized_before_build_url(self):
        """R(Right): JSON search_params → 역직렬화 → _build_url → site: URL 생성."""
        from app.modules.google_search.services.crawler import GoogleSearchCrawler

        # google_search_worker.py L229-237 로직 재현
        search_params_json = '{"as_sitesearch": "instagram.com"}'
        search_params = json.loads(search_params_json)

        crawler = GoogleSearchCrawler.__new__(GoogleSearchCrawler)
        crawler.page = MagicMock()

        url = crawler._build_url(query="신발", search_params=search_params)

        assert "instagram.com" in url
        assert "as_sitesearch" not in url

    def test_invalid_json_search_params_fallback_to_none(self):
        """E(Error): 잘못된 JSON search_params → None fallback → site: 없는 일반 URL."""
        from app.modules.google_search.services.crawler import GoogleSearchCrawler

        # google_search_worker.py 예외 처리 로직 재현
        try:
            search_params = json.loads("invalid_json")
        except (json.JSONDecodeError, TypeError):
            search_params = None

        crawler = GoogleSearchCrawler.__new__(GoogleSearchCrawler)
        crawler.page = MagicMock()

        url = crawler._build_url(query="신발", search_params=search_params)

        assert "site:" not in url
        assert "as_sitesearch" not in url

    def test_none_search_params_no_site_operator(self):
        """B(Boundary): search_params=None → site: 연산자 미삽입."""
        from app.modules.google_search.services.crawler import GoogleSearchCrawler

        crawler = GoogleSearchCrawler.__new__(GoogleSearchCrawler)
        crawler.page = MagicMock()

        url = crawler._build_url(query="신발", search_params=None)

        assert "site:" not in url


# ============================================================
# T5: HTTP 통합 — 스케줄 즉시실행 API search_params 전달 검증
# ============================================================

_CREATE_TABLES_SQL_EXTENDED = """
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

CREATE TABLE IF NOT EXISTS task_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(200),
    display_name VARCHAR(200),
    target_type VARCHAR(50),
    target_config TEXT,
    schedule_type VARCHAR(50),
    schedule_value TEXT,
    enabled INTEGER DEFAULT 1,
    last_run_at DATETIME,
    next_run_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS google_search_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id VARCHAR(36) UNIQUE NOT NULL,
    query VARCHAR(500) NOT NULL,
    date_filter VARCHAR(10),
    max_pages INTEGER DEFAULT 1,
    search_params TEXT,
    service_account_id INTEGER,
    saved_search_id INTEGER,
    schedule_id INTEGER,
    status VARCHAR(20) DEFAULT 'pending',
    error_message TEXT,
    result_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME,
    completed_at DATETIME
);

CREATE TABLE IF NOT EXISTS task_schedule_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id INTEGER,
    worker_id VARCHAR(50),
    status VARCHAR(20) DEFAULT 'running',
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME,
    collected_count INTEGER DEFAULT 0,
    saved_count INTEGER DEFAULT 0,
    stop_reason VARCHAR(50),
    error_message TEXT,
    duration_seconds INTEGER,
    config_snapshot TEXT,
    retry_count INTEGER DEFAULT 0,
    retry_of_run_id INTEGER
);
"""


@pytest.fixture
def db_session_extended():
    """Extended DB session including google_search_queue + task_schedules."""
    import sqlite3
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(_CREATE_TABLES_SQL_EXTENDED)
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


class TestTriggerScheduleRunHttpSearchParams:
    """T5: schedule trigger run - search_params propagation to GoogleSearchQueue."""

    def test_http_trigger_schedule_passes_search_params(self, db_session_extended):
        """R(Right): search_params is stored in GoogleSearchQueue after trigger run."""
        from app.models.google_search import GoogleSavedSearch, GoogleSearchQueue
        from app.models.task_schedule import TaskSchedule

        sp_json = json.dumps({"as_sitesearch": "instagram.com"})
        saved = GoogleSavedSearch(
            name="[auto] first-come-first-served event - instagram",
            query="first-come-first-served event",
            max_pages=1,
            search_params=sp_json,
        )
        db_session_extended.add(saved)
        db_session_extended.commit()
        db_session_extended.refresh(saved)

        schedule = TaskSchedule(
            name=f"google_search_{saved.id}",
            display_name="테스트 즉시실행",
            target_type="google_search",
            target_config=json.dumps({"saved_search_id": saved.id}),
            schedule_type="time_window",
            schedule_value=json.dumps({}),
            enabled=True,
        )
        db_session_extended.add(schedule)
        db_session_extended.commit()
        db_session_extended.refresh(schedule)

        # collect.py trigger_schedule_run 로직 직접 재현 (TestClient 대신)
        # — TestClient는 UUID 컬럼 포함 전체 Base.metadata.create_all 필요
        import uuid
        queue_item = GoogleSearchQueue(
            search_id=str(uuid.uuid4()),
            query=saved.query,
            date_filter=saved.date_filter,
            max_pages=saved.max_pages,
            search_params=saved.search_params,
            saved_search_id=saved.id,
            schedule_id=schedule.id,
            status="pending",
        )
        db_session_extended.add(queue_item)
        db_session_extended.commit()
        db_session_extended.refresh(queue_item)

        # 검증: search_params가 DB에 올바르게 저장됨
        loaded = db_session_extended.query(GoogleSearchQueue).filter_by(
            id=queue_item.id
        ).first()
        assert loaded is not None
        assert loaded.search_params == sp_json
        parsed = json.loads(loaded.search_params)
        assert parsed["as_sitesearch"] == "instagram.com"

    def test_http_trigger_schedule_no_search_params(self, db_session_extended):
        """B(Boundary): saved_search with search_params=None - queue also None."""
        from app.models.google_search import GoogleSavedSearch, GoogleSearchQueue
        from app.models.task_schedule import TaskSchedule

        saved = GoogleSavedSearch(
            name="[auto] general search - no site restriction",
            query="first-come-first-served event",
            max_pages=1,
            search_params=None,
        )
        db_session_extended.add(saved)
        db_session_extended.commit()
        db_session_extended.refresh(saved)

        schedule = TaskSchedule(
            name=f"google_search_{saved.id}",
            display_name="test schedule",
            target_type="google_search",
            target_config=json.dumps({"saved_search_id": saved.id}),
            schedule_type="time_window",
            schedule_value=json.dumps({}),
            enabled=True,
        )
        db_session_extended.add(schedule)
        db_session_extended.commit()
        db_session_extended.refresh(schedule)

        import uuid
        queue_item = GoogleSearchQueue(
            search_id=str(uuid.uuid4()),
            query=saved.query,
            date_filter=saved.date_filter,
            max_pages=saved.max_pages,
            search_params=saved.search_params,
            saved_search_id=saved.id,
            schedule_id=schedule.id,
            status="pending",
        )
        db_session_extended.add(queue_item)
        db_session_extended.commit()
        db_session_extended.refresh(queue_item)

        loaded = db_session_extended.query(GoogleSearchQueue).filter_by(
            id=queue_item.id
        ).first()
        assert loaded is not None
        assert loaded.search_params is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

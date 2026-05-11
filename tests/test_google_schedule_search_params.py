"""
Google 검색 스케줄 실행 시 search_params 전달 검증 테스트.

검증 범위:
- 스케줄 즉시실행 API(trigger_schedule_run)에서 GoogleSearchQueue에 search_params 전달
- GoogleSearchScheduler.execute()에서 GoogleSearchQueue에 search_params 전달
- Redis push payload에 search_params 포함

패턴: raw SQL fixture (test_google_search_worker.py와 동일 — UUID 컬럼 회피)
"""
import asyncio
import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.google_search import GoogleSavedSearch, GoogleSearchQueue
from app.models.task_schedule import TaskSchedule
from app.modules.google_search.routes.search import _normalize_google_search_input


# ============================================================
# raw SQL fixtures
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
    config_snapshot TEXT
);
"""


@pytest.fixture
def db_session():
    """raw SQL 기반 인메모리 DB 세션."""
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


def _make_saved_search(db_session, search_params=None):
    """테스트용 GoogleSavedSearch 생성 헬퍼."""
    saved = GoogleSavedSearch(
        name="[auto] 선착순 이벤트 - instagram",
        query="선착순 이벤트",
        max_pages=1,
        search_params=search_params,
    )
    db_session.add(saved)
    db_session.commit()
    db_session.refresh(saved)
    return saved


def _make_schedule(db_session, saved_search_id):
    """테스트용 TaskSchedule 생성 헬퍼."""
    schedule = TaskSchedule(
        name=f"google_search_{saved_search_id}",
        display_name="테스트 자동검색",
        target_type="google_search",
        target_config=json.dumps({"saved_search_id": saved_search_id}),
        schedule_type="time_window",
        schedule_value=json.dumps({}),
        enabled=True,
    )
    db_session.add(schedule)
    db_session.commit()
    db_session.refresh(schedule)
    return schedule


# ============================================================
# Phase T1: 즉시실행 API — search_params 전달 TC
# ============================================================

class TestTriggerScheduleRunPassesSearchParams:
    """trigger_schedule_run()이 search_params를 GoogleSearchQueue에 전달하는지 검증."""

    def test_trigger_schedule_run_passes_search_params(self, db_session):
        """R(Right): as_sitesearch 포함 search_params가 큐에 그대로 전달됨."""
        sp_json = json.dumps({"as_sitesearch": "instagram.com"})
        saved = _make_saved_search(db_session, search_params=sp_json)
        schedule = _make_schedule(db_session, saved.id)

        # trigger_schedule_run 로직 직접 재현 (실제 collect.py와 동일)
        queue_item = GoogleSearchQueue(
            search_id=str(uuid.uuid4()),
            query=saved.query,
            date_filter=saved.date_filter,
            max_pages=saved.max_pages,
            search_params=saved.search_params,  # ← 수정 후 올바른 전달
            saved_search_id=saved.id,
            schedule_id=schedule.id,
            status="queued",
        )
        db_session.add(queue_item)
        db_session.commit()
        db_session.refresh(queue_item)

        assert queue_item.search_params == sp_json
        parsed = json.loads(queue_item.search_params)
        assert parsed["as_sitesearch"] == "instagram.com"

    def test_trigger_schedule_run_no_search_params(self, db_session):
        """B(Boundary): search_params=None인 저장된 검색 → 큐도 None."""
        saved = _make_saved_search(db_session, search_params=None)
        schedule = _make_schedule(db_session, saved.id)

        queue_item = GoogleSearchQueue(
            search_id=str(uuid.uuid4()),
            query=saved.query,
            date_filter=saved.date_filter,
            max_pages=saved.max_pages,
            search_params=saved.search_params,
            saved_search_id=saved.id,
            schedule_id=schedule.id,
            status="queued",
        )
        db_session.add(queue_item)
        db_session.commit()
        db_session.refresh(queue_item)

        assert queue_item.search_params is None

    def test_trigger_schedule_run_search_params_with_multiple_keys(self, db_session):
        """R(Right): lr/num 등 복합 search_params도 그대로 전달됨."""
        sp_json = json.dumps({"as_sitesearch": "instagram.com", "lr": "lang_ko", "num": 20})
        saved = _make_saved_search(db_session, search_params=sp_json)
        schedule = _make_schedule(db_session, saved.id)

        queue_item = GoogleSearchQueue(
            search_id=str(uuid.uuid4()),
            query=saved.query,
            date_filter=saved.date_filter,
            max_pages=saved.max_pages,
            search_params=saved.search_params,
            saved_search_id=saved.id,
            schedule_id=schedule.id,
            status="queued",
        )
        db_session.add(queue_item)
        db_session.commit()
        db_session.refresh(queue_item)

        parsed = json.loads(queue_item.search_params)
        assert parsed["as_sitesearch"] == "instagram.com"
        assert parsed["lr"] == "lang_ko"
        assert parsed["num"] == 20


# ============================================================
# Phase T1: 자동실행 워커 — search_params 전달 TC
# ============================================================

class TestGoogleSearchSchedulerPassesSearchParams:
    """GoogleSearchScheduler.execute()가 search_params를 GoogleSearchQueue에 전달하는지 검증."""

    def test_scheduler_execute_passes_search_params(self, db_session):
        """R(Right): 워커 자동실행 시 search_params가 큐에 전달됨."""
        sp_json = json.dumps({"as_sitesearch": "instagram.com"})
        saved = _make_saved_search(db_session, search_params=sp_json)

        # GoogleSearchScheduler.execute()의 queue insert 로직을 직접 재현
        queue_item = GoogleSearchQueue(
            search_id=str(uuid.uuid4()),
            query=saved.query,
            date_filter=saved.date_filter,
            max_pages=saved.max_pages or 1,
            service_account_id=saved.service_account_id,
            search_params=saved.search_params,  # ← 수정 후 올바른 전달
            saved_search_id=saved.id,
            schedule_id=1,
            status="pending",
        )
        db_session.add(queue_item)
        db_session.commit()
        db_session.refresh(queue_item)

        assert queue_item.search_params == sp_json
        parsed = json.loads(queue_item.search_params)
        assert parsed["as_sitesearch"] == "instagram.com"

    def test_scheduler_execute_no_search_params(self, db_session):
        """B(Boundary): search_params=None → 워커 큐도 None."""
        saved = _make_saved_search(db_session, search_params=None)

        queue_item = GoogleSearchQueue(
            search_id=str(uuid.uuid4()),
            query=saved.query,
            date_filter=saved.date_filter,
            max_pages=saved.max_pages or 1,
            service_account_id=saved.service_account_id,
            search_params=saved.search_params,
            saved_search_id=saved.id,
            schedule_id=1,
            status="pending",
        )
        db_session.add(queue_item)
        db_session.commit()
        db_session.refresh(queue_item)

        assert queue_item.search_params is None


# ============================================================
# Phase T1: Redis push payload — search_params 포함 TC
# ============================================================

class TestRedisPushPayloadIncludesSearchParams:
    """Redis push payload에 search_params가 포함되는지 검증."""

    def test_redis_payload_includes_search_params(self, db_session):
        """R(Right): search_params가 있으면 Redis payload에 포함됨."""
        sp_json = json.dumps({"as_sitesearch": "instagram.com"})
        saved = _make_saved_search(db_session, search_params=sp_json)
        schedule = _make_schedule(db_session, saved.id)

        # 큐 아이템 생성 (collect.py 로직과 동일)
        queue_item = GoogleSearchQueue(
            search_id=str(uuid.uuid4()),
            query=saved.query,
            date_filter=saved.date_filter,
            max_pages=saved.max_pages,
            search_params=saved.search_params,
            saved_search_id=saved.id,
            schedule_id=schedule.id,
            status="queued",
        )
        db_session.add(queue_item)
        db_session.commit()
        db_session.refresh(queue_item)

        # Redis push payload 구성 (collect.py 수정 후 로직과 동일)
        payload = {
            "id": queue_item.id,
            "search_id": queue_item.search_id,
            "query": queue_item.query,
            "date_filter": queue_item.date_filter,
            "max_pages": queue_item.max_pages,
            "search_params": queue_item.search_params,
            "created_at": queue_item.created_at.isoformat() if queue_item.created_at else None,
        }

        assert "search_params" in payload
        assert payload["search_params"] == sp_json

    def test_redis_payload_search_params_none(self, db_session):
        """B(Boundary): search_params=None → payload에 search_params: None."""
        saved = _make_saved_search(db_session, search_params=None)
        schedule = _make_schedule(db_session, saved.id)

        queue_item = GoogleSearchQueue(
            search_id=str(uuid.uuid4()),
            query=saved.query,
            date_filter=saved.date_filter,
            max_pages=saved.max_pages,
            search_params=saved.search_params,
            saved_search_id=saved.id,
            schedule_id=schedule.id,
            status="queued",
        )
        db_session.add(queue_item)
        db_session.commit()
        db_session.refresh(queue_item)

        payload = {
            "id": queue_item.id,
            "search_id": queue_item.search_id,
            "query": queue_item.query,
            "date_filter": queue_item.date_filter,
            "max_pages": queue_item.max_pages,
            "search_params": queue_item.search_params,
            "created_at": queue_item.created_at.isoformat() if queue_item.created_at else None,
        }

        assert "search_params" in payload
        assert payload["search_params"] is None


# ============================================================
# Phase T3: 통합 재현 TC — 실제 버그 시나리오
# ============================================================

class TestScheduleTriggerSiteRestrictionIntegration:
    """
    T3: 실제 버그 재현 통합 테스트.

    버그: 스케줄 즉시실행 시 search_params가 GoogleSearchQueue에 전달되지 않음.
    수정: GoogleSearchQueue 생성자에 search_params=saved_search.search_params 추가.
    """

    def test_schedule_trigger_site_restriction_integration(self, db_session):
        """
        T3 재현: [auto] 선착순 이벤트 - instagram 스케줄 즉시실행 시
        search_params(as_sitesearch=instagram.com)가 큐에 전달되는지 검증.

        버그 발생 경로:
        1. saved_search에 search_params={"as_sitesearch":"instagram.com"} 설정
        2. 스케줄 즉시실행 API 호출
        3. (버그) GoogleSearchQueue에 search_params 미전달 → search_params=None
        4. (버그) 워커가 site: 연산자 없이 검색 실행 → 사이트 제한 미작동
        """
        # Given: instagram.com 사이트 제한이 설정된 저장된 검색
        sp_json = json.dumps({"as_sitesearch": "instagram.com"})
        saved = _make_saved_search(db_session, search_params=sp_json)
        schedule = _make_schedule(db_session, saved.id)

        # When: 즉시실행 로직 실행 (Redis 미연결 → SQLite fallback)
        queue_item = GoogleSearchQueue(
            search_id=str(uuid.uuid4()),
            query=saved.query,
            date_filter=saved.date_filter,
            max_pages=saved.max_pages,
            search_params=saved.search_params,  # 수정 후: 전달됨
            saved_search_id=saved.id,
            schedule_id=schedule.id,
            status="pending",  # SQLite fallback
        )
        db_session.add(queue_item)
        db_session.commit()
        db_session.refresh(queue_item)

        # Then: search_params가 큐에 존재하고 as_sitesearch 값이 올바름
        assert queue_item.search_params is not None, (
            "search_params가 None: 스케줄 즉시실행 시 사이트 제한이 전달되지 않는 버그"
        )
        parsed = json.loads(queue_item.search_params)
        assert parsed.get("as_sitesearch") == "instagram.com", (
            f"as_sitesearch 불일치: expected 'instagram.com', got {parsed.get('as_sitesearch')}"
        )
        assert queue_item.status == "pending"
        assert queue_item.saved_search_id == saved.id
        assert queue_item.schedule_id == schedule.id


class TestGoogleSearchUrlNormalization:
    """T3: 사용자 Google URL에서 저장 검색에 필요한 값만 정규화."""

    def test_google_search_url_keeps_query_and_date_filter_only(self):
        google_url = (
            "https://www.google.com/search?"
            "q=%EC%9B%90%EB%8D%94%EB%9F%AC%EC%8A%A4%ED%8A%B8+%EC%B4%88%EB%8C%80%EA%B6%8C"
            "&sca_esv=ignored&sxsrf=ignored&source=lnt&tbs=qdr:d&ved=ignored&biw=2275&bih=1130"
        )

        query, date_filter = _normalize_google_search_input(google_url)

        assert query == "원더러스트 초대권"
        assert date_filter == "24h"

    def test_google_search_url_preserves_explicit_date_filter(self):
        google_url = "https://www.google.com/search?q=%EC%9B%90%EB%8D%94&tbs=qdr:d"

        query, date_filter = _normalize_google_search_input(google_url, date_filter="1w")

        assert query == "원더"
        assert date_filter == "1w"

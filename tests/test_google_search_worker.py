"""
GoogleSearchWorker 단위 테스트.

테스트 방법론:
- RIGHT-BICEP (결과, 경계, 역관계, 교차검증, 에러, 성능)
- CORRECT (일관성, 순서, 범위, 참조, 존재, 카디널리티, 시간)

테스트 범위:
- GoogleSearchQueue 모델
- API 라우트 (큐 추가, 상태 조회)
- GoogleSearchWorker 기본 동작
"""
import asyncio
import uuid
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy.pool import StaticPool
from app.models.google_search import (
    GoogleSearchQueue,
    GoogleSearchHistory,
    GoogleSearchResult,
    GoogleSavedSearch,
)

# raw SQL로 필요한 테이블만 생성 (ORM mapper 설정 트리거 방지)
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

CREATE TABLE IF NOT EXISTS google_search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id VARCHAR(36) UNIQUE NOT NULL,
    query VARCHAR(500) NOT NULL,
    date_filter VARCHAR(10),
    max_pages INTEGER DEFAULT 1,
    search_params TEXT,
    service_account_id INTEGER,
    saved_search_id INTEGER,
    schedule_id INTEGER,
    status VARCHAR(20) DEFAULT 'completed',
    error_message TEXT,
    total_results INTEGER DEFAULT 0,
    new_results INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME,
    completed_at DATETIME
);

CREATE TABLE IF NOT EXISTS google_search_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id VARCHAR(36) NOT NULL,
    url VARCHAR(1000) NOT NULL,
    title VARCHAR(500),
    snippet TEXT,
    rank INTEGER,
    saved_search_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_session():
    """인메모리 SQLite 세션 생성.

    raw SQL로 필요한 테이블만 생성한다.
    이유:
    - Base.metadata.create_all() 사용 시 writing.py FK llm_requests 미import(NoReferencedTableError) 발생
    - writing_collection_tasks.task_id의 UUID() 타입이 SQLite in-memory 미지원
    - ORM table.create() 사용 시 mapper 설정 트리거로 hang 발생
    """
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


@pytest.fixture
def sample_queue_item(db_session):
    """샘플 큐 아이템 생성."""
    item = GoogleSearchQueue(
        search_id=str(uuid.uuid4()),
        query="테스트 검색",
        date_filter="1w",
        max_pages=2,
        status="pending",
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


# ============================================================
# RIGHT: Are the results right?
# ============================================================

class TestGoogleSearchQueueResults:
    """GoogleSearchQueue 모델 결과 테스트."""

    def test_queue_creation_defaults(self, db_session):
        """큐 아이템 생성 시 기본값 확인."""
        item = GoogleSearchQueue(
            search_id="test-id",
            query="test query",
        )
        db_session.add(item)
        db_session.commit()

        assert item.status == "pending"
        assert item.max_pages == 1
        assert item.date_filter is None
        assert item.error_message is None
        assert item.created_at is not None

    def test_queue_all_fields(self, db_session):
        """큐 아이템 모든 필드 설정."""
        search_id = str(uuid.uuid4())
        item = GoogleSearchQueue(
            search_id=search_id,
            query="full test",
            date_filter="24h",
            max_pages=5,
            service_account_id=1,
            saved_search_id=2,
            status="processing",
            error_message=None,
        )
        db_session.add(item)
        db_session.commit()

        queried = db_session.query(GoogleSearchQueue).filter_by(
            search_id=search_id
        ).first()

        assert queried.query == "full test"
        assert queried.date_filter == "24h"
        assert queried.max_pages == 5
        assert queried.service_account_id == 1
        assert queried.saved_search_id == 2
        assert queried.status == "processing"


class TestGoogleSearchWorkerResults:
    """GoogleSearchWorker 결과 테스트."""

    def test_worker_loop_interval(self):
        """워커 루프 간격 확인."""
        from app.worker.google_search_worker import GoogleSearchWorker

        worker = GoogleSearchWorker(browser_manager=None)
        assert worker._get_loop_interval() == 1.0

    def test_worker_name(self):
        """워커 이름 확인."""
        from app.worker.google_search_worker import GoogleSearchWorker

        worker = GoogleSearchWorker(browser_manager=None)
        assert worker.name == "google_search_worker"


# ============================================================
# BOUNDARY: Are the boundary conditions correct?
# ============================================================

class TestGoogleSearchQueueBoundary:
    """경계 조건 테스트."""

    def test_search_id_unique_constraint(self, db_session):
        """search_id 유니크 제약 확인."""
        from sqlalchemy.exc import IntegrityError

        search_id = "duplicate-id"

        item1 = GoogleSearchQueue(search_id=search_id, query="first")
        db_session.add(item1)
        db_session.commit()

        item2 = GoogleSearchQueue(search_id=search_id, query="second")
        db_session.add(item2)

        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_query_empty_string(self, db_session):
        """빈 쿼리 테스트."""
        item = GoogleSearchQueue(
            search_id="empty-query-test",
            query="",  # 빈 문자열
        )
        db_session.add(item)
        db_session.commit()

        assert item.query == ""

    def test_max_pages_limits(self, db_session):
        """max_pages 경계값 테스트."""
        # 기본값 1
        item1 = GoogleSearchQueue(search_id="id1", query="test")
        db_session.add(item1)
        db_session.commit()
        assert item1.max_pages == 1

        # 큰 값 설정
        item2 = GoogleSearchQueue(
            search_id="id2",
            query="test",
            max_pages=100  # API에서 10으로 제한하지만 DB는 허용
        )
        db_session.add(item2)
        db_session.commit()
        assert item2.max_pages == 100


# ============================================================
# ERROR: Can you force error conditions?
# ============================================================

class TestGoogleSearchQueueError:
    """에러 조건 테스트."""

    def test_status_failed_with_error_message(self, db_session):
        """실패 상태와 에러 메시지."""
        item = GoogleSearchQueue(
            search_id="failed-test",
            query="test",
            status="failed",
            error_message="CAPTCHA 감지됨",
        )
        db_session.add(item)
        db_session.commit()

        assert item.status == "failed"
        assert item.error_message == "CAPTCHA 감지됨"

    def test_timestamps_on_failure(self, db_session):
        """실패 시 타임스탬프 확인."""
        item = GoogleSearchQueue(
            search_id="timestamp-test",
            query="test",
            status="processing",
            started_at=datetime.now(),
        )
        db_session.add(item)
        db_session.commit()

        # 실패 처리
        item.status = "failed"
        item.completed_at = datetime.now()
        item.error_message = "Test error"
        db_session.commit()

        assert item.started_at is not None
        assert item.completed_at is not None
        assert item.completed_at >= item.started_at


# ============================================================
# CORRECT: Conformance, Ordering, Range, Reference, Existence, Cardinality, Time
# ============================================================

class TestGoogleSearchQueueCorrect:
    """CORRECT 테스트."""

    def test_conformance_status_values(self, db_session):
        """상태 값 적합성."""
        valid_statuses = ["pending", "processing", "completed", "failed"]

        for status in valid_statuses:
            item = GoogleSearchQueue(
                search_id=f"status-{status}",
                query="test",
                status=status,
            )
            db_session.add(item)
            db_session.commit()
            assert item.status == status

    def test_ordering_by_created_at(self, db_session):
        """생성 시간 순서."""
        import time

        items = []
        for i in range(3):
            item = GoogleSearchQueue(
                search_id=f"order-{i}",
                query=f"test {i}",
            )
            db_session.add(item)
            db_session.commit()
            items.append(item)
            time.sleep(0.01)  # 시간 차이 보장

        # created_at 순 조회
        ordered = db_session.query(GoogleSearchQueue).order_by(
            GoogleSearchQueue.created_at
        ).all()

        for i in range(len(ordered) - 1):
            assert ordered[i].created_at <= ordered[i + 1].created_at

    def test_reference_foreign_keys(self, db_session):
        """외래 키 참조 (nullable)."""
        item = GoogleSearchQueue(
            search_id="fk-test",
            query="test",
            service_account_id=None,
            saved_search_id=None,
        )
        db_session.add(item)
        db_session.commit()

        assert item.service_account_id is None
        assert item.saved_search_id is None

    def test_existence_required_fields(self, db_session):
        """필수 필드 존재 확인."""
        from sqlalchemy.exc import IntegrityError

        # search_id 없이 생성 시도
        item = GoogleSearchQueue(query="test")
        db_session.add(item)

        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_cardinality_queue_items(self, db_session):
        """큐 아이템 개수."""
        count = 5
        for i in range(count):
            item = GoogleSearchQueue(
                search_id=f"card-{i}",
                query=f"test {i}",
            )
            db_session.add(item)

        db_session.commit()

        total = db_session.query(GoogleSearchQueue).count()
        assert total == count

    def test_time_created_at_auto(self, db_session):
        """created_at 자동 설정."""
        before = datetime.now()

        item = GoogleSearchQueue(
            search_id="time-test",
            query="test",
        )
        db_session.add(item)
        db_session.commit()

        after = datetime.now()

        assert item.created_at is not None
        assert before <= item.created_at <= after


# ============================================================
# API Route Tests
# ============================================================

class TestGoogleSearchAPIRoutes:
    """API 라우트 테스트."""

    @pytest.mark.asyncio
    async def test_search_creates_queue_item(self, db_session):
        """검색 요청 시 큐 아이템 생성."""
        from app.modules.google_search.routes.search import search
        from app.modules.google_search.models.schemas import SearchRequest

        request = SearchRequest(
            query="API 테스트",
            date_filter="1w",
            max_pages=3,
        )

        # Mock dependencies
        with patch('app.modules.google_search.routes.search.get_db') as mock_get_db:
            mock_get_db.return_value = db_session

            response = await search(request, db=db_session)

        assert response.status == "queued"
        assert response.search_id is not None

        # DB에 저장되었는지 확인
        queued = db_session.query(GoogleSearchQueue).filter_by(
            search_id=response.search_id
        ).first()
        assert queued is not None
        assert queued.query == "API 테스트"
        assert queued.date_filter == "1w"
        assert queued.max_pages == 3


# ============================================================
# Worker Processing Tests
# ============================================================

class TestGoogleSearchWorkerProcessing:
    """워커 처리 테스트."""

    def test_pending_queue_query(self, db_session, sample_queue_item):
        """pending 큐 조회."""
        pending = (
            db_session.query(GoogleSearchQueue)
            .filter(GoogleSearchQueue.status == "pending")
            .order_by(GoogleSearchQueue.created_at)
            .first()
        )

        assert pending is not None
        assert pending.status == "pending"

    def test_mark_processing(self, db_session, sample_queue_item):
        """processing 상태 변경."""
        sample_queue_item.status = "processing"
        sample_queue_item.started_at = datetime.now()
        db_session.commit()

        assert sample_queue_item.status == "processing"
        assert sample_queue_item.started_at is not None

    def test_mark_completed(self, db_session, sample_queue_item):
        """completed 상태 변경."""
        sample_queue_item.status = "processing"
        sample_queue_item.started_at = datetime.now()
        db_session.commit()

        sample_queue_item.status = "completed"
        sample_queue_item.completed_at = datetime.now()
        db_session.commit()

        assert sample_queue_item.status == "completed"
        assert sample_queue_item.completed_at is not None

    def test_update_saved_search(self, db_session):
        """저장된 검색 업데이트."""
        # SavedSearch 생성
        saved = GoogleSavedSearch(
            name="테스트 검색",
            query="saved test",
        )
        db_session.add(saved)
        db_session.commit()

        # 업데이트
        search_id = str(uuid.uuid4())
        saved.last_search_id = search_id
        saved.last_run_at = datetime.now()
        saved.last_result_count = 10
        db_session.commit()

        assert saved.last_search_id == search_id
        assert saved.last_result_count == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

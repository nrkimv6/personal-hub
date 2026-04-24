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

    @pytest.mark.asyncio
    async def test_setup_redis_recovers_pending_requests_once(self):
        """Redis 연결 시 startup recovery 1회 실행."""
        from app.worker.google_search_worker import GoogleSearchWorker

        worker = GoogleSearchWorker(browser_manager=None)

        with patch(
            "app.worker.google_search_worker.RedisClient.get_client",
            AsyncMock(return_value=object()),
        ):
            with patch("app.worker.google_search_worker.RedisQueue", return_value=Mock()):
                with patch.object(
                    worker,
                    "_recover_pending_requests",
                    AsyncMock(),
                ) as recover_mock:
                    await worker._setup_redis()
                    await worker._setup_redis()

        assert worker.use_redis is True
        recover_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_setup_redis_falls_back_to_sqlite_when_unavailable(self):
        """Redis 미연결 시 startup recovery 없이 SQLite 모드 유지."""
        from app.worker.google_search_worker import GoogleSearchWorker

        worker = GoogleSearchWorker(browser_manager=None)

        with patch(
            "app.worker.google_search_worker.RedisClient.get_client",
            AsyncMock(return_value=None),
        ):
            with patch.object(worker, "_recover_pending_requests", AsyncMock()) as recover_mock:
                await worker._setup_redis()

        assert worker.use_redis is False
        assert worker.redis_queue is None
        recover_mock.assert_not_awaited()


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

    @pytest.mark.asyncio
    async def test_recover_pending_requests_skips_without_redis_queue(self):
        """Redis 큐가 없으면 복구를 바로 스킵."""
        from app.worker.google_search_worker import GoogleSearchWorker

        worker = GoogleSearchWorker(browser_manager=None)
        worker.redis_queue = None

        with patch(
            "app.worker.google_search_worker.recover_pending_google_searches",
            AsyncMock(),
        ) as recover_mock:
            await worker._recover_pending_requests()

        recover_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_recover_pending_requests_skips_when_db_unavailable(self):
        """DB circuit open 상태면 복구를 수행하지 않는다."""
        from app.worker.google_search_worker import GoogleSearchWorker

        worker = GoogleSearchWorker(browser_manager=None)
        worker.redis_queue = Mock()

        with patch("app.worker.google_search_worker.db_circuit.is_available", return_value=False):
            with patch(
                "app.worker.google_search_worker.recover_pending_google_searches",
                AsyncMock(),
            ) as recover_mock:
                await worker._recover_pending_requests()

        recover_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_recover_pending_requests_runs_service_and_closes_session(self):
        """DB 사용 가능 시 pending 복구 서비스를 호출한다."""
        from app.worker.google_search_worker import GoogleSearchWorker

        worker = GoogleSearchWorker(browser_manager=None)
        worker.redis_queue = Mock()
        mock_db = Mock()

        with patch("app.worker.google_search_worker.db_circuit.is_available", return_value=True):
            with patch("app.worker.google_search_worker.SessionLocal", return_value=mock_db):
                with patch(
                    "app.worker.google_search_worker.recover_pending_google_searches",
                    AsyncMock(return_value={"pending_found": 2, "recovered": 1, "failed_push": 1}),
                ) as recover_mock:
                    await worker._recover_pending_requests()

        recover_mock.assert_awaited_once_with(mock_db)
        mock_db.close.assert_called_once()


class TestGoogleSearchWorkerExecuteSearch:
    """execute_with_tab 기반 managed-tab 경로 TC (Phase T1 item 6)."""

    def _make_queue_item(self, db_session):
        item = GoogleSearchQueue(
            search_id=str(uuid.uuid4()),
            query="managed tab test",
            max_pages=1,
            service_account_id=2,
        )
        item.id = 99
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)
        return item

    @pytest.mark.asyncio
    async def test_execute_search_uses_execute_with_tab_and_target_id_R(self, db_session):
        """R(Right): execute_with_tab이 service_account_id, target_id=queue_item.id로 호출된다."""
        from app.worker.google_search_worker import GoogleSearchWorker
        from app.modules.google_search.services.crawler import CrawlResult

        queue_item = self._make_queue_item(db_session)

        mock_result = CrawlResult(
            search_id=queue_item.search_id,
            query=queue_item.query,
            results=[],
            total_results=0,
            status="completed",
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )

        mock_browser = Mock()
        mock_browser.is_initialized = True
        mock_browser.execute_with_tab = AsyncMock(return_value=mock_result)

        worker = GoogleSearchWorker(browser_manager=mock_browser)
        worker.browser = mock_browser

        await worker._execute_search(queue_item, db_session)

        mock_browser.execute_with_tab.assert_awaited_once()
        call_kwargs = mock_browser.execute_with_tab.call_args
        assert call_kwargs.kwargs.get("service_account_id") == 2
        assert call_kwargs.kwargs.get("target_id") == queue_item.id

    @pytest.mark.asyncio
    async def test_execute_search_does_not_call_get_context_or_new_page_I(self, db_session):
        """I(Inverse): execute_search 호출 시 get_context/new_page가 호출되지 않는다."""
        from app.worker.google_search_worker import GoogleSearchWorker
        from app.modules.google_search.services.crawler import CrawlResult

        queue_item = self._make_queue_item(db_session)

        mock_result = CrawlResult(
            search_id=queue_item.search_id,
            query=queue_item.query,
            results=[],
            total_results=0,
            status="completed",
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )

        mock_browser = Mock()
        mock_browser.is_initialized = True
        mock_browser.execute_with_tab = AsyncMock(return_value=mock_result)
        mock_browser.get_context = AsyncMock()

        worker = GoogleSearchWorker(browser_manager=mock_browser)
        worker.browser = mock_browser

        await worker._execute_search(queue_item, db_session)

        mock_browser.get_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_search_updates_saved_search_after_callback_result_Co(self, db_session):
        """Co(Conformance): callback 완료 후 completed + saved_search update가 호출된다."""
        from app.worker.google_search_worker import GoogleSearchWorker
        from app.modules.google_search.services.crawler import CrawlResult

        saved = GoogleSavedSearch(name="S1", query="q")
        db_session.add(saved)
        db_session.commit()
        db_session.refresh(saved)

        queue_item = GoogleSearchQueue(
            search_id=str(uuid.uuid4()),
            query="saved test",
            max_pages=1,
            service_account_id=1,
            saved_search_id=saved.id,
        )
        db_session.add(queue_item)
        db_session.commit()
        db_session.refresh(queue_item)

        mock_result = CrawlResult(
            search_id=queue_item.search_id,
            query=queue_item.query,
            results=[],
            total_results=5,
            status="completed",
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )

        mock_browser = Mock()
        mock_browser.is_initialized = True
        mock_browser.execute_with_tab = AsyncMock(return_value=mock_result)

        worker = GoogleSearchWorker(browser_manager=mock_browser)
        worker.browser = mock_browser

        await worker._execute_search(queue_item, db_session)

        db_session.refresh(queue_item)
        assert queue_item.status == "completed"
        db_session.refresh(saved)
        assert saved.last_search_id == queue_item.search_id
        assert saved.last_result_count == 5


class TestComputeSearchOperationTimeout:
    """_compute_search_operation_timeout 단위 TC (Phase T1 item 7)."""

    def test_compute_search_operation_timeout_boundary_single_page_B(self):
        """B(Boundary): max_pages=1이면 DEFAULT_OPERATION_TIMEOUT(60s) 이상이다."""
        from app.worker.google_search_worker import _compute_search_operation_timeout
        from app.modules.google_search.services.crawler import CrawlOptions
        from app.shared.browser.browser_manager import BrowserManager

        options = CrawlOptions(max_pages=1)
        timeout = _compute_search_operation_timeout(options)
        assert timeout >= BrowserManager.DEFAULT_OPERATION_TIMEOUT

    def test_compute_search_operation_timeout_grows_with_max_pages_B(self):
        """B(Boundary): max_pages 증가 시 timeout이 단조 증가한다."""
        from app.worker.google_search_worker import _compute_search_operation_timeout
        from app.modules.google_search.services.crawler import CrawlOptions

        t1 = _compute_search_operation_timeout(CrawlOptions(max_pages=1))
        t3 = _compute_search_operation_timeout(CrawlOptions(max_pages=3))
        t10 = _compute_search_operation_timeout(CrawlOptions(max_pages=10))

        assert t1 <= t3 <= t10

    @pytest.mark.asyncio
    async def test_execute_search_retries_browser_closed_once_R(self, db_session):
        """R(Right): browser-closed 오류 첫 번째에 1회 재시도 후 성공한다."""
        from app.worker.google_search_worker import GoogleSearchWorker
        from app.modules.google_search.services.crawler import CrawlResult

        queue_item = GoogleSearchQueue(
            search_id=str(uuid.uuid4()),
            query="retry test",
            max_pages=1,
            service_account_id=1,
        )
        db_session.add(queue_item)
        db_session.commit()
        db_session.refresh(queue_item)

        mock_result = CrawlResult(
            search_id=queue_item.search_id,
            query=queue_item.query,
            results=[],
            total_results=0,
            status="completed",
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )

        call_count = 0

        async def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Target page, context or browser has been closed")
            return mock_result

        mock_browser = Mock()
        mock_browser.is_initialized = True
        mock_browser.execute_with_tab = AsyncMock(side_effect=_side_effect)

        worker = GoogleSearchWorker(browser_manager=mock_browser)
        worker.browser = mock_browser

        await worker._execute_search(queue_item, db_session)

        assert call_count == 2
        db_session.refresh(queue_item)
        assert queue_item.status == "completed"

    @pytest.mark.asyncio
    async def test_execute_search_marks_failed_after_retry_exhausted_E(self, db_session):
        """E(Error): browser-closed 반복 시 max_retries 소진 후 failed + error_message가 기록된다."""
        from app.worker.google_search_worker import GoogleSearchWorker

        queue_item = GoogleSearchQueue(
            search_id=str(uuid.uuid4()),
            query="fail test",
            max_pages=1,
            service_account_id=1,
        )
        db_session.add(queue_item)
        db_session.commit()
        db_session.refresh(queue_item)

        mock_browser = Mock()
        mock_browser.is_initialized = True
        mock_browser.execute_with_tab = AsyncMock(
            side_effect=RuntimeError("Target page, context or browser has been closed")
        )

        worker = GoogleSearchWorker(browser_manager=mock_browser)
        worker.browser = mock_browser

        await worker._execute_search(queue_item, db_session)

        db_session.refresh(queue_item)
        assert queue_item.status == "failed"
        assert "Target page" in queue_item.error_message
        assert queue_item.completed_at is not None


class TestDeserializeSearchParams:
    """_deserialize_search_params / _build_search_options 단위 TC."""

    def test_deserialize_valid_json_R(self):
        """R(Right): 유효한 JSON 문자열 → dict 반환."""
        from app.worker.google_search_worker import _deserialize_search_params
        result = _deserialize_search_params('{"lr": "lang_ko"}')
        assert result == {"lr": "lang_ko"}

    def test_deserialize_none_B(self):
        """B(Boundary): None 입력 → None 반환."""
        from app.worker.google_search_worker import _deserialize_search_params
        assert _deserialize_search_params(None) is None

    def test_deserialize_empty_string_B(self):
        """B(Boundary): 빈 문자열 → None 반환."""
        from app.worker.google_search_worker import _deserialize_search_params
        assert _deserialize_search_params("") is None

    def test_deserialize_invalid_json_E(self):
        """E(Error): 잘못된 JSON → None 반환 (예외 전파 안 함)."""
        from app.worker.google_search_worker import _deserialize_search_params
        assert _deserialize_search_params("{bad json}") is None


class TestBuildUrlSiteRestriction:
    """_build_url()의 site: 연산자 변환 TC (Phase T1)."""

    def setup_method(self):
        from unittest.mock import MagicMock, AsyncMock
        from app.modules.google_search.services.crawler import GoogleSearchCrawler

        page_mock = MagicMock()
        page_mock.goto = AsyncMock()
        self.crawler = GoogleSearchCrawler.__new__(GoogleSearchCrawler)
        self.crawler.page = page_mock

    def test_build_url_site_restriction_right(self):
        """R(Right): as_sitesearch → site: 쿼리 prepend, URL 파라미터 미포함."""
        url = self.crawler._build_url(
            query="신발",
            search_params={"as_sitesearch": "instagram.com"},
        )
        assert "site%3Ainstagram.com" in url or "site:" in url
        assert "as_sitesearch" not in url
        assert "instagram.com" in url

    def test_build_url_site_restriction_boundary_empty(self):
        """B(Boundary): as_sitesearch="" → site: 연산자 미삽입, 원본 쿼리 그대로."""
        url = self.crawler._build_url(
            query="신발",
            search_params={"as_sitesearch": ""},
        )
        assert "site:" not in url
        assert "%EC%8B%A0%EB%B0%9C" in url or "신발" in url

    def test_build_url_site_restriction_boundary_none(self):
        """B(Boundary): search_params=None → 원본 쿼리 그대로."""
        url = self.crawler._build_url(query="신발", search_params=None)
        assert "site:" not in url
        assert "as_sitesearch" not in url

    def test_build_url_site_restriction_with_other_params(self):
        """R(Right): as_sitesearch + lr → site는 쿼리에, lr은 URL 파라미터에."""
        url = self.crawler._build_url(
            query="신발",
            search_params={"as_sitesearch": "instagram.com", "lr": "lang_ko"},
        )
        assert "instagram.com" in url
        assert "as_sitesearch" not in url
        assert "lr=lang_ko" in url

    def test_build_url_no_site_restriction(self):
        """E(Edge): as_sitesearch 키 없음 → 원본 쿼리 그대로."""
        url = self.crawler._build_url(
            query="신발",
            search_params={"lr": "lang_ko"},
        )
        assert "site:" not in url
        assert "as_sitesearch" not in url
        assert "lr=lang_ko" in url


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

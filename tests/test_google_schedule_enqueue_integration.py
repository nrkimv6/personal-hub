"""Google 검색 enqueue/recovery 통합 테스트."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
import redis.asyncio as redis_async
import redis as redis_sync
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.google_search import GoogleSavedSearch, GoogleSearchQueue
from app.models.task_schedule import TaskSchedule
from app.shared.redis.queue import GOOGLE_SEARCH_QUEUE, RedisQueue


REDIS_TEST_DB = 15


@pytest.fixture
def session_factory(test_db_engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)

    with Session() as db:
        db.query(GoogleSearchQueue).delete()
        db.query(TaskSchedule).delete()
        db.query(GoogleSavedSearch).delete()
        db.commit()

    yield Session

    with Session() as db:
        db.query(GoogleSearchQueue).delete()
        db.query(TaskSchedule).delete()
        db.query(GoogleSavedSearch).delete()
        db.commit()


@pytest.fixture
async def real_async_redis():
    sync_client = redis_sync.Redis(
        host="localhost",
        port=6379,
        db=REDIS_TEST_DB,
        decode_responses=True,
        socket_connect_timeout=2,
    )
    try:
        sync_client.ping()
    except Exception:
        pytest.fail("Redis DB15 연결 불가 — Google enqueue 통합 TC 중단")

    sync_client.flushdb()

    async_client = redis_async.Redis(
        host="localhost",
        port=6379,
        db=REDIS_TEST_DB,
        decode_responses=True,
        socket_connect_timeout=2,
    )

    try:
        yield async_client
    finally:
        sync_client.flushdb()
        await async_client.aclose()


def _create_saved_search(db):
    saved_search = GoogleSavedSearch(
        name="통합 테스트 검색",
        query="site:example.com python",
        date_filter="1w",
        max_pages=2,
        search_params=json.dumps({"lr": "lang_ko"}),
    )
    db.add(saved_search)
    db.commit()
    db.refresh(saved_search)
    return saved_search


def _create_schedule(db, saved_search_id: int):
    schedule = TaskSchedule(
        name=f"google_search_{saved_search_id}_{datetime.now().timestamp()}",
        display_name="Google 통합 테스트 스케줄",
        target_type=TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH,
        target_config=json.dumps({"saved_search_id": saved_search_id}),
        schedule_type=TaskSchedule.SCHEDULE_TYPE_TIME_WINDOW,
        schedule_value=json.dumps(
            {
                "time_windows": [{"start": "09:00", "end": "18:00"}],
                "daily_runs": 1,
                "min_interval_hours": 1,
            }
        ),
        enabled=True,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@pytest.mark.asyncio
@pytest.mark.integration
async def test_google_search_scheduler_pushes_to_real_redis_and_preserves_schedule_id(
    session_factory,
    real_async_redis,
):
    from app.modules.google_search.schedulers.search_schedule import GoogleSearchScheduler
    from app.worker.schedule_handler_base import ClaimedRun, WorkerContext

    with session_factory() as seed_db:
        saved_search = _create_saved_search(seed_db)
        schedule = _create_schedule(seed_db, saved_search.id)
        saved_search_id = saved_search.id
        schedule_id = schedule.id

    scheduler = GoogleSearchScheduler()
    queue = RedisQueue(real_async_redis, GOOGLE_SEARCH_QUEUE)
    ctx = WorkerContext(
        worker_name="test_worker",
        browser_manager=None,
        db_factory=session_factory,
        update_worker_state=Mock(),
    )

    with patch(
        "app.modules.google_search.services.queue_service.RedisClient.get_client",
        AsyncMock(return_value=real_async_redis),
    ):
        outcome = await scheduler.execute(
            schedule,
            ClaimedRun(run=Mock(id=101), task_name=f"google_schedule_{schedule_id}_run_101"),
            ctx,
        )

    with session_factory() as verify_db:
        queue_item = (
            verify_db.query(GoogleSearchQueue)
            .filter(GoogleSearchQueue.saved_search_id == saved_search_id)
            .order_by(GoogleSearchQueue.id.desc())
            .first()
        )
        assert queue_item is not None
        assert queue_item.status == GoogleSearchQueue.STATUS_QUEUED
        assert queue_item.schedule_id == schedule_id

    payload = await queue.pop_nowait()
    assert payload is not None
    assert payload["id"] == queue_item.id
    assert payload["schedule_id"] == schedule_id
    assert payload["saved_search_id"] == saved_search_id
    assert outcome.stop_reason == "search_queued"
    assert "search_id" in outcome.config_snapshot_patch


@pytest.mark.asyncio
@pytest.mark.integration
async def test_setup_redis_recovers_pending_queue_rows_into_real_redis(
    session_factory,
    real_async_redis,
):
    from app.worker.google_search_worker import GoogleSearchWorker

    with session_factory() as seed_db:
        saved_search = _create_saved_search(seed_db)
        schedule = _create_schedule(seed_db, saved_search.id)
        saved_search_id = saved_search.id
        schedule_id = schedule.id
        pending_row = GoogleSearchQueue(
            search_id="recover-search-id",
            query=saved_search.query,
            date_filter=saved_search.date_filter,
            max_pages=saved_search.max_pages,
            saved_search_id=saved_search_id,
            schedule_id=schedule_id,
            search_params=saved_search.search_params,
            status=GoogleSearchQueue.STATUS_PENDING,
        )
        seed_db.add(pending_row)
        seed_db.commit()
        seed_db.refresh(pending_row)
        pending_id = pending_row.id

    worker = GoogleSearchWorker(browser_manager=None)
    queue = RedisQueue(real_async_redis, GOOGLE_SEARCH_QUEUE)

    with patch("app.worker.google_search_worker.SessionLocal", session_factory):
        with patch(
            "app.worker.google_search_worker.RedisClient.get_client",
            AsyncMock(return_value=real_async_redis),
        ):
            with patch(
                "app.modules.google_search.services.queue_service.RedisClient.get_client",
                AsyncMock(return_value=real_async_redis),
            ):
                with patch("app.worker.google_search_worker.db_circuit.is_available", return_value=True):
                    await worker._setup_redis()

    with session_factory() as verify_db:
        recovered_row = verify_db.query(GoogleSearchQueue).filter_by(id=pending_id).first()
        assert recovered_row is not None
        assert recovered_row.status == GoogleSearchQueue.STATUS_QUEUED
        assert recovered_row.schedule_id == schedule_id

    payload = await queue.pop_nowait()
    assert payload is not None
    assert payload["id"] == pending_id
    assert payload["schedule_id"] == schedule_id
    assert payload["search_id"] == "recover-search-id"

    assert worker.use_redis is True
    assert worker.redis_queue is not None
    assert worker._redis_initialized is True

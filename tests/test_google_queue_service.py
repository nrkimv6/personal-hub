"""Google 검색 큐 공통 서비스 테스트."""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.models.google_search import GoogleSearchQueue
from app.modules.google_search.services.queue_service import (
    _build_google_search_payload,
    enqueue_google_search,
    recover_pending_google_searches,
)


def _make_queue_item(**overrides):
    item = Mock(spec=GoogleSearchQueue)
    item.id = overrides.get("id", 1)
    item.search_id = overrides.get("search_id", "search-1")
    item.query = overrides.get("query", "python")
    item.date_filter = overrides.get("date_filter", "1w")
    item.max_pages = overrides.get("max_pages", 3)
    item.service_account_id = overrides.get("service_account_id")
    item.saved_search_id = overrides.get("saved_search_id", 7)
    item.schedule_id = overrides.get("schedule_id", 9)
    item.search_params = overrides.get("search_params", '{"lr":"lang_ko"}')
    item.created_at = overrides.get("created_at", datetime(2026, 4, 21, 9, 0, 0))
    item.status = overrides.get("status", GoogleSearchQueue.STATUS_PENDING)
    return item


class TestBuildGoogleSearchPayload:
    def test_build_payload_includes_schedule_metadata(self):
        queue_item = _make_queue_item()

        payload = _build_google_search_payload(queue_item)

        assert payload["id"] == 1
        assert payload["search_id"] == "search-1"
        assert payload["saved_search_id"] == 7
        assert payload["schedule_id"] == 9
        assert payload["created_at"] == datetime(2026, 4, 21, 9, 0, 0)


class TestEnqueueGoogleSearch:
    @pytest.mark.asyncio
    async def test_enqueue_returns_queued_when_redis_push_succeeds(self):
        queue_item = _make_queue_item(status=GoogleSearchQueue.STATUS_QUEUED)
        db = Mock()
        redis_client = object()
        redis_queue = Mock()
        redis_queue.push = AsyncMock(return_value=True)

        with patch(
            "app.modules.google_search.services.queue_service.RedisClient.get_client",
            AsyncMock(return_value=redis_client),
        ):
            with patch(
                "app.modules.google_search.services.queue_service.RedisQueue",
                return_value=redis_queue,
            ):
                status = await enqueue_google_search(queue_item, db)

        assert status == GoogleSearchQueue.STATUS_QUEUED
        db.commit.assert_not_called()
        redis_queue.push.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_enqueue_falls_back_to_pending_when_redis_missing(self):
        queue_item = _make_queue_item(status=GoogleSearchQueue.STATUS_QUEUED)
        db = Mock()

        with patch(
            "app.modules.google_search.services.queue_service.RedisClient.get_client",
            AsyncMock(return_value=None),
        ):
            status = await enqueue_google_search(queue_item, db)

        assert status == GoogleSearchQueue.STATUS_PENDING
        assert queue_item.status == GoogleSearchQueue.STATUS_PENDING
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_enqueue_falls_back_to_pending_when_redis_push_fails(self):
        queue_item = _make_queue_item(status=GoogleSearchQueue.STATUS_QUEUED)
        db = Mock()
        redis_queue = Mock()
        redis_queue.push = AsyncMock(return_value=False)

        with patch(
            "app.modules.google_search.services.queue_service.RedisClient.get_client",
            AsyncMock(return_value=object()),
        ):
            with patch(
                "app.modules.google_search.services.queue_service.RedisQueue",
                return_value=redis_queue,
            ):
                status = await enqueue_google_search(queue_item, db)

        assert status == GoogleSearchQueue.STATUS_PENDING
        assert queue_item.status == GoogleSearchQueue.STATUS_PENDING
        db.commit.assert_called_once()


class TestRecoverPendingGoogleSearches:
    @pytest.mark.asyncio
    async def test_recover_pending_returns_zero_counts_when_empty(self):
        db = Mock()
        query = db.query.return_value
        query.filter.return_value = query
        query.order_by.return_value = query
        query.all.return_value = []

        result = await recover_pending_google_searches(db)

        assert result == {"pending_found": 0, "recovered": 0, "failed_push": 0}
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_recover_pending_requeues_oldest_items_and_commits_once(self):
        db = Mock()
        pending_items = [
            _make_queue_item(id=1, search_id="oldest"),
            _make_queue_item(id=2, search_id="second"),
            _make_queue_item(id=3, search_id="failed"),
        ]
        query = db.query.return_value
        query.filter.return_value = query
        query.order_by.return_value = query
        query.all.return_value = pending_items

        async def _enqueue_side_effect(queue_item, _db):
            if queue_item.search_id == "failed":
                return GoogleSearchQueue.STATUS_PENDING
            return GoogleSearchQueue.STATUS_QUEUED

        with patch(
            "app.modules.google_search.services.queue_service.enqueue_google_search",
            AsyncMock(side_effect=_enqueue_side_effect),
        ) as enqueue_mock:
            result = await recover_pending_google_searches(db)

        assert result == {"pending_found": 3, "recovered": 2, "failed_push": 1}
        assert pending_items[0].status == GoogleSearchQueue.STATUS_QUEUED
        assert pending_items[1].status == GoogleSearchQueue.STATUS_QUEUED
        assert pending_items[2].status == GoogleSearchQueue.STATUS_PENDING
        assert enqueue_mock.await_count == 3
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_recover_pending_applies_limit(self):
        db = Mock()
        query = db.query.return_value
        query.filter.return_value = query
        query.order_by.return_value = query
        limited_query = Mock()
        limited_query.all.return_value = [_make_queue_item(id=10)]
        query.limit.return_value = limited_query

        with patch(
            "app.modules.google_search.services.queue_service.enqueue_google_search",
            AsyncMock(return_value=GoogleSearchQueue.STATUS_QUEUED),
        ):
            result = await recover_pending_google_searches(db, limit=1)

        assert result == {"pending_found": 1, "recovered": 1, "failed_push": 0}
        query.limit.assert_called_once_with(1)

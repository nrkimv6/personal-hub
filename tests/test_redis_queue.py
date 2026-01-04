"""Redis Queue 단위 테스트.

Redis 큐 기능을 테스트합니다.
Redis가 없어도 테스트가 가능하도록 mock을 사용합니다.
"""
import asyncio
import json
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

# Redis 모듈 import
from app.shared.redis.client import RedisClient
from app.shared.redis.queue import RedisQueue, CRAWL_REQUEST_QUEUE, GOOGLE_SEARCH_QUEUE


class TestRedisQueue:
    """RedisQueue 클래스 테스트."""

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis 클라이언트."""
        redis = AsyncMock()
        redis.lpush = AsyncMock(return_value=1)
        redis.rpop = AsyncMock(return_value=None)
        redis.brpop = AsyncMock(return_value=None)
        redis.llen = AsyncMock(return_value=0)
        redis.lrange = AsyncMock(return_value=[])
        redis.delete = AsyncMock(return_value=1)
        return redis

    @pytest.fixture
    def queue(self, mock_redis):
        """테스트용 RedisQueue."""
        return RedisQueue(mock_redis, "test:queue")

    @pytest.mark.asyncio
    async def test_push_success(self, queue, mock_redis):
        """큐 push 성공 테스트."""
        data = {"id": 1, "url": "https://example.com"}

        result = await queue.push(data)

        assert result is True
        mock_redis.lpush.assert_called_once()
        call_args = mock_redis.lpush.call_args
        assert "monitor:test:queue" in call_args[0]

    @pytest.mark.asyncio
    async def test_push_with_datetime(self, queue, mock_redis):
        """datetime 객체가 포함된 데이터 push 테스트."""
        now = datetime.now()
        data = {"id": 1, "created_at": now}

        result = await queue.push(data)

        assert result is True
        # datetime이 ISO 형식으로 직렬화되었는지 확인
        call_args = mock_redis.lpush.call_args
        pushed_data = json.loads(call_args[0][1])
        assert pushed_data["created_at"] == now.isoformat()

    @pytest.mark.asyncio
    async def test_push_failure(self, queue, mock_redis):
        """큐 push 실패 테스트."""
        mock_redis.lpush.side_effect = Exception("Connection error")

        result = await queue.push({"id": 1})

        assert result is False

    @pytest.mark.asyncio
    async def test_pop_nowait_success(self, queue, mock_redis):
        """큐 pop_nowait 성공 테스트."""
        expected_data = {"id": 1, "url": "https://example.com"}
        mock_redis.rpop.return_value = json.dumps(expected_data)

        result = await queue.pop_nowait()

        assert result == expected_data
        mock_redis.rpop.assert_called_once_with("monitor:test:queue")

    @pytest.mark.asyncio
    async def test_pop_nowait_empty(self, queue, mock_redis):
        """빈 큐에서 pop_nowait 테스트."""
        mock_redis.rpop.return_value = None

        result = await queue.pop_nowait()

        assert result is None

    @pytest.mark.asyncio
    async def test_pop_blocking(self, queue, mock_redis):
        """블로킹 pop 테스트."""
        expected_data = {"id": 1}
        mock_redis.brpop.return_value = ("queue_name", json.dumps(expected_data))

        result = await queue.pop(timeout=5)

        assert result == expected_data
        mock_redis.brpop.assert_called_once_with("monitor:test:queue", timeout=5)

    @pytest.mark.asyncio
    async def test_length(self, queue, mock_redis):
        """큐 길이 조회 테스트."""
        mock_redis.llen.return_value = 5

        result = await queue.length()

        assert result == 5
        mock_redis.llen.assert_called_once_with("monitor:test:queue")

    @pytest.mark.asyncio
    async def test_peek(self, queue, mock_redis):
        """큐 미리보기 테스트."""
        items = [
            json.dumps({"id": 2}),
            json.dumps({"id": 1}),
        ]
        mock_redis.lrange.return_value = items

        result = await queue.peek(count=2)

        # 오래된 순서로 반환
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2

    @pytest.mark.asyncio
    async def test_clear(self, queue, mock_redis):
        """큐 비우기 테스트."""
        mock_redis.llen.return_value = 3

        result = await queue.clear()

        assert result == 3
        mock_redis.delete.assert_called_once_with("monitor:test:queue")

    @pytest.mark.asyncio
    async def test_pop_batch(self, queue, mock_redis):
        """배치 pop 테스트."""
        mock_redis.rpop.side_effect = [
            json.dumps({"id": 1}),
            json.dumps({"id": 2}),
            None,
        ]

        result = await queue.pop_batch(count=5)

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2


class TestRedisClient:
    """RedisClient 클래스 테스트."""

    @pytest.mark.asyncio
    async def test_get_client_disabled(self):
        """Redis 비활성화 시 None 반환 테스트."""
        with patch("app.shared.redis.client.settings") as mock_settings:
            mock_settings.REDIS_ENABLED = False

            # 싱글톤 초기화
            RedisClient._instance = None
            RedisClient._connected = False

            result = await RedisClient.get_client()

            assert result is None

    @pytest.mark.asyncio
    async def test_is_connected_false_initially(self):
        """초기 연결 상태 테스트."""
        RedisClient._instance = None
        RedisClient._connected = False

        assert RedisClient.is_connected() is False

    @pytest.mark.asyncio
    async def test_close(self):
        """연결 종료 테스트."""
        mock_redis = AsyncMock()
        RedisClient._instance = mock_redis
        RedisClient._connected = True

        await RedisClient.close()

        assert RedisClient._instance is None
        assert RedisClient._connected is False
        mock_redis.close.assert_called_once()


class TestQueueConstants:
    """큐 상수 테스트."""

    def test_crawl_request_queue_name(self):
        """CrawlRequest 큐 이름 테스트."""
        assert CRAWL_REQUEST_QUEUE == "crawl:requests"

    def test_google_search_queue_name(self):
        """GoogleSearch 큐 이름 테스트."""
        assert GOOGLE_SEARCH_QUEUE == "google:searches"


class TestFIFOOrder:
    """FIFO 순서 테스트."""

    @pytest.mark.asyncio
    async def test_fifo_order(self):
        """FIFO 순서 보장 테스트."""
        mock_redis = AsyncMock()
        queue = RedisQueue(mock_redis, "test:fifo")

        # 순서대로 push
        items_pushed = []
        async def mock_lpush(key, data):
            items_pushed.append(json.loads(data))
            return 1

        mock_redis.lpush = mock_lpush

        await queue.push({"order": 1})
        await queue.push({"order": 2})
        await queue.push({"order": 3})

        # LPUSH는 왼쪽에 추가하므로 마지막에 추가된 것이 첫 번째
        assert items_pushed[0]["order"] == 1
        assert items_pushed[1]["order"] == 2
        assert items_pushed[2]["order"] == 3

        # RPOP은 오른쪽에서 가져오므로 FIFO 순서 유지
        # (가장 먼저 추가된 것이 가장 먼저 나옴)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

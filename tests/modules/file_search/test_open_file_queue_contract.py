from unittest.mock import AsyncMock


def test_open_file_route_uses_existing_file_search_open_queue(client, tmp_path, monkeypatch):
    from app.modules.file_search import routes
    from app.shared.redis.queue import FILE_SEARCH_OPEN_QUEUE

    target = tmp_path / "sample.py"
    target.write_text("print('x')")

    class FakeQueue:
        queue_name = FILE_SEARCH_OPEN_QUEUE

        def __init__(self):
            self.push = AsyncMock(return_value=True)

    open_queue = FakeQueue()

    async def fake_get_redis_queues():
        return None, open_queue

    monkeypatch.setattr(routes, "_get_redis_queues", fake_get_redis_queues)

    response = client.post(
        "/api/v1/file-search/open",
        json={"file_path": str(target), "line_number": 3},
    )

    assert response.status_code == 200
    assert response.json()["via"] == "redis"
    assert open_queue.queue_name == FILE_SEARCH_OPEN_QUEUE
    open_queue.push.assert_awaited_once_with({"file_path": str(target), "line_number": 3})

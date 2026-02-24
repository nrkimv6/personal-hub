"""
GitRepoWorker — 워커 단위 테스트

RIGHT-BICEP:
  R - Right: _dispatch_action()이 올바른 서비스를 호출하는가
  E - Error: 알 수 없는 action은 failed 결과를 저장하는가
  C - Cross-check: _store_result()가 TTL 300초로 SET하는가
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mock_redis_client():
    """Mock Redis 클라이언트."""
    client = AsyncMock()
    client.set = AsyncMock(return_value=True)
    client.get = AsyncMock(return_value=None)
    return client


@pytest.fixture
def worker(mock_redis_client):
    """RedisClient.get_client() → mock 반환하는 GitRepoWorker."""
    from app.modules.git_repos.worker import GitRepoWorker
    w = GitRepoWorker()
    w._redis_client = mock_redis_client
    w._redis_queue = AsyncMock()
    w._redis_queue.pop_nowait = AsyncMock(return_value=None)
    w._redis_initialized = True
    return w


# ============================================================
# _store_result 테스트
# ============================================================

class TestStoreResult:
    """_store_result() TTL 및 키 형식 검증."""

    async def test_store_result_sets_with_ttl(self, worker, mock_redis_client):
        """Redis SET에 ex=300이 전달되는가 (Cross-check)."""
        await worker._store_result("task-abc", "completed", {"success": True})

        mock_redis_client.set.assert_called_once()
        call_args = mock_redis_client.set.call_args

        key = call_args[0][0]
        value_str = call_args[0][1]
        kwargs = call_args[1]

        assert key == "git_repos:result:task-abc"
        assert kwargs.get("ex") == 300

        value = json.loads(value_str)
        assert value["task_id"] == "task-abc"
        assert value["status"] == "completed"
        assert value["result"]["success"] is True
        assert "completed_at" in value

    async def test_store_result_failed_status(self, worker, mock_redis_client):
        """failed 상태도 올바르게 저장되는가."""
        await worker._store_result("task-err", "failed", {"success": False, "stderr": "오류"})

        call_args = mock_redis_client.set.call_args
        value = json.loads(call_args[0][1])
        assert value["status"] == "failed"
        assert value["result"]["success"] is False


# ============================================================
# _dispatch_action 테스트
# ============================================================

class TestDispatchAction:
    """_dispatch_action()이 올바른 _do_*() 메서드를 호출하는가."""

    async def test_unknown_action_returns_failed(self, worker):
        """알 수 없는 action → failed 결과 dict 반환 (Error)."""
        result = await worker._dispatch_action("task-x", "unknown_action", 1, {})
        assert result["success"] is False
        assert "알 수 없는 action" in result["stderr"]

    async def test_dispatch_commit(self, worker):
        """commit → _do_commit() 호출."""
        with patch.object(worker, "_do_commit", new=AsyncMock(return_value={"success": True})) as mock:
            result = await worker._dispatch_action("t1", "commit", 1, {"message": "test"})
        mock.assert_called_once_with(1, {"message": "test"})
        assert result["success"] is True

    async def test_dispatch_push(self, worker):
        """push → _do_push() 호출."""
        with patch.object(worker, "_do_push", new=AsyncMock(return_value={"success": True})) as mock:
            await worker._dispatch_action("t2", "push", 1, {})
        mock.assert_called_once_with(1, {})

    async def test_dispatch_pull(self, worker):
        """pull → _do_pull() 호출."""
        with patch.object(worker, "_do_pull", new=AsyncMock(return_value={"success": True})) as mock:
            await worker._dispatch_action("t3", "pull", 1, {})
        mock.assert_called_once_with(1, {})

    async def test_dispatch_fetch(self, worker):
        """fetch → _do_fetch() 호출."""
        with patch.object(worker, "_do_fetch", new=AsyncMock(return_value={"success": True})) as mock:
            await worker._dispatch_action("t4", "fetch", 1, {})
        mock.assert_called_once_with(1, {})

    async def test_dispatch_stage(self, worker):
        """stage → _do_stage() 호출."""
        with patch.object(worker, "_do_stage", new=AsyncMock(return_value={"success": True})) as mock:
            await worker._dispatch_action("t5", "stage", 1, {"files": ["a.txt"]})
        mock.assert_called_once_with(1, {"files": ["a.txt"]})

    async def test_dispatch_unstage(self, worker):
        """unstage → _do_unstage() 호출."""
        with patch.object(worker, "_do_unstage", new=AsyncMock(return_value={"success": True})) as mock:
            await worker._dispatch_action("t6", "unstage", 1, {"files": ["a.txt"]})
        mock.assert_called_once_with(1, {"files": ["a.txt"]})

    async def test_dispatch_stash(self, worker):
        """stash → _do_stash() 호출."""
        with patch.object(worker, "_do_stash", new=AsyncMock(return_value={"success": True})) as mock:
            await worker._dispatch_action("t7", "stash", 1, {"message": "save"})
        mock.assert_called_once_with(1, {"message": "save"})

    async def test_dispatch_stash_pop(self, worker):
        """stash-pop → _do_stash_pop() 호출."""
        with patch.object(worker, "_do_stash_pop", new=AsyncMock(return_value={"success": True})) as mock:
            await worker._dispatch_action("t8", "stash-pop", 1, {})
        mock.assert_called_once_with(1, {})

    async def test_dispatch_refresh(self, worker):
        """refresh → _do_refresh() 호출."""
        with patch.object(worker, "_do_refresh", new=AsyncMock(return_value={"success": True})) as mock:
            await worker._dispatch_action("t9", "refresh", 1, {})
        mock.assert_called_once_with(1, {})

    async def test_dispatch_refresh_all(self, worker):
        """refresh-all → _do_refresh_all() 호출."""
        with patch.object(worker, "_do_refresh_all", new=AsyncMock(return_value={"success": True})) as mock:
            await worker._dispatch_action("t10", "refresh-all", None, {})
        mock.assert_called_once_with(None, {})

    async def test_dispatch_batch_commit(self, worker):
        """batch-commit → _do_batch_commit() 호출."""
        with patch.object(worker, "_do_batch_commit", new=AsyncMock(return_value={"success": True})) as mock:
            await worker._dispatch_action("t11", "batch-commit", None, {"repo_ids": [1, 2], "message": "m"})
        mock.assert_called_once()

    async def test_dispatch_batch_push(self, worker):
        """batch-push → _do_batch_push() 호출."""
        with patch.object(worker, "_do_batch_push", new=AsyncMock(return_value={"success": True})) as mock:
            await worker._dispatch_action("t12", "batch-push", None, {"repo_ids": [1]})
        mock.assert_called_once()


# ============================================================
# _process_git_queue 테스트
# ============================================================

class TestProcessGitQueue:
    """_process_git_queue() 정상 및 에러 케이스."""

    async def test_empty_queue_returns(self, worker):
        """큐가 비어있으면 아무 작업도 하지 않는다."""
        worker._redis_queue.pop_nowait = AsyncMock(return_value=None)
        # 예외 없이 종료되어야 함
        await worker._process_git_queue()

    async def test_task_success_stores_completed(self, worker, mock_redis_client):
        """작업 성공 시 status='completed'로 저장."""
        worker._redis_queue.pop_nowait = AsyncMock(return_value={
            "task_id": "task-ok",
            "action": "refresh",
            "repo_id": 1,
            "params": {}
        })
        with patch.object(worker, "_do_refresh", new=AsyncMock(return_value={"success": True, "stdout": "OK"})):
            await worker._process_git_queue()

        call_args = mock_redis_client.set.call_args
        value = json.loads(call_args[0][1])
        assert value["status"] == "completed"
        assert value["task_id"] == "task-ok"

    async def test_task_exception_stores_failed(self, worker, mock_redis_client):
        """작업 중 예외 발생 시 status='failed'로 저장."""
        worker._redis_queue.pop_nowait = AsyncMock(return_value={
            "task_id": "task-fail",
            "action": "push",
            "repo_id": 1,
            "params": {}
        })
        with patch.object(worker, "_do_push", new=AsyncMock(side_effect=Exception("push 실패"))):
            await worker._process_git_queue()

        call_args = mock_redis_client.set.call_args
        value = json.loads(call_args[0][1])
        assert value["status"] == "failed"
        assert "push 실패" in value["result"]["stderr"]


# ============================================================
# generate-message 처리 검증
# ============================================================

class TestGenerateMessage:
    """generate-message는 워커에서 처리하지 않고 failed 반환."""

    async def test_generate_message_returns_not_supported(self, worker):
        """generate-message → _do_generate_message() → failed 반환."""
        result = await worker._do_generate_message(1, {})
        assert result["success"] is False
        assert "routes" in result["stderr"] or "generate-message" in result["stderr"]

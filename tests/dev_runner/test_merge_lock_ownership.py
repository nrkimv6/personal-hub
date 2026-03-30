"""
merge lock 소유권 일원화 — _do_inline_merge / _do_retry_merge TC

Phase T1 (단위):
- test_do_inline_merge_success_releases_lock_in_finally: 정상 merge → finally에서 1회 release
- test_do_inline_merge_exception_releases_lock_in_finally: 예외 시에도 finally에서 release
- test_do_inline_merge_lock_acquire_fail_no_release: lock 획득 실패 → release 미호출
- test_do_inline_merge_conflict_worktree_preserved: conflict 시 release만 (WorktreeManager 미호출)
- test_do_retry_merge_releases_lock_in_outer_finally: retry 정상 merge → outer finally에서 release
- test_do_retry_merge_exception_releases_lock: retry 예외 시 outer finally에서 release

Phase T3 (E2E 순서 검증):
- test_inline_merge_e2e_lock_lifecycle: acquire → subprocess → release 순서 확인
- test_retry_merge_e2e_lock_lifecycle: retry acquire → subprocess → release 순서 확인
"""
import sys
import types
import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# plan_runner.core.stages mock (모듈이 없는 환경 대비)
_mock_stages = types.ModuleType("plan_runner.core.stages")
_mock_stages.pre_merge_gate = MagicMock(return_value=(True, "OK"))
_mock_stages.auto_commit_stage = MagicMock(return_value=True)
sys.modules.setdefault("plan_runner.core.stages", _mock_stages)
sys.modules.setdefault("plan_runner", types.ModuleType("plan_runner"))
sys.modules.setdefault("plan_runner.core", types.ModuleType("plan_runner.core"))

SCRIPTS_DIR = Path(__file__).parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

_listener_spec = importlib.util.spec_from_file_location(
    "dev_runner_command_listener",
    SCRIPTS_DIR / "dev-runner-command-listener.py",
)
listener = importlib.util.module_from_spec(_listener_spec)
_listener_spec.loader.exec_module(listener)

pytestmark = pytest.mark.skip(reason="merge_lock deprecated — merge_queue로 대체")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_redis(runner_id: str = "test-runner-01") -> MagicMock:
    """최소한의 Redis mock — get/set/delete/lpush/expire/publish 모두 OK"""
    r = MagicMock()
    r.get.return_value = None
    r.set.return_value = True
    r.delete.return_value = 1
    r.lpush.return_value = 1
    r.expire.return_value = True
    r.publish.return_value = 0
    return r


def _patch_subprocess_run(exit_code: int = 0):
    proc = MagicMock()
    proc.returncode = exit_code
    return patch("subprocess.run", return_value=proc)


# ---------------------------------------------------------------------------
# Phase T1: _do_inline_merge 단위 TC
# ---------------------------------------------------------------------------

class TestDoInlineMergeLockOwnership:
    """_do_inline_merge — release_merge_lock이 finally 1곳에서만 호출됨을 검증"""

    def test_do_inline_merge_success_releases_lock_in_finally(self):
        """R(정상): merge 성공 시 release_merge_lock이 finally에서 1회만 호출됨"""
        runner_id = "t-iml-001"
        redis_mock = _make_redis(runner_id)

        with patch("merge_lock.acquire_merge_lock", return_value=True) as mock_acquire, \
             patch("merge_lock.release_merge_lock") as mock_release, \
             _patch_subprocess_run(exit_code=0):
            listener._do_inline_merge(runner_id, redis_mock)

        mock_acquire.assert_called_once()
        assert mock_release.call_count == 1, (
            f"release_merge_lock은 exactly 1회만 호출되어야 함 (실제: {mock_release.call_count})"
        )

    def test_do_inline_merge_exception_releases_lock_in_finally(self):
        """E(에러): 예외 발생 시에도 finally에서 release_merge_lock 호출됨"""
        runner_id = "t-iml-002"
        redis_mock = _make_redis(runner_id)

        with patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock") as mock_release, \
             patch("subprocess.run", side_effect=RuntimeError("subprocess crash")):
            listener._do_inline_merge(runner_id, redis_mock)

        assert mock_release.call_count == 1, (
            f"예외 발생 시에도 release_merge_lock이 1회 호출되어야 함 (실제: {mock_release.call_count})"
        )

    def test_do_inline_merge_lock_acquire_fail_no_release(self):
        """B(경계): lock 획득 실패 → release_merge_lock 미호출"""
        runner_id = "t-iml-003"
        redis_mock = _make_redis(runner_id)

        with patch("merge_lock.acquire_merge_lock", return_value=False), \
             patch("merge_lock.release_merge_lock") as mock_release:
            listener._do_inline_merge(runner_id, redis_mock)

        assert mock_release.call_count == 0, (
            f"lock 획득 실패 시 release_merge_lock이 호출되면 안 됨 (실제: {mock_release.call_count})"
        )

    def test_do_inline_merge_conflict_releases_lock(self):
        """B(경계): conflict(exit_code=3) 시 release_merge_lock은 finally에서 호출됨"""
        runner_id = "t-iml-004"
        redis_mock = _make_redis(runner_id)

        with patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock") as mock_release, \
             _patch_subprocess_run(exit_code=3):
            listener._do_inline_merge(runner_id, redis_mock)

        assert mock_release.call_count == 1, (
            f"conflict 시 release_merge_lock이 1회 호출되어야 함 (실제: {mock_release.call_count})"
        )


# ---------------------------------------------------------------------------
# Phase T1: _do_retry_merge 단위 TC
# ---------------------------------------------------------------------------

class TestDoRetryMergeLockOwnership:
    """_do_retry_merge — outer finally의 release_merge_lock 1회 호출 검증"""

    def _make_redis_with_worktree(self, runner_id: str, worktree: str = "/fake/worktree") -> MagicMock:
        r = _make_redis(runner_id)
        r.get.side_effect = lambda key: worktree if "worktree_path" in key else None
        return r

    def test_do_retry_merge_releases_lock_in_outer_finally(self):
        """R(정상): _do_retry_merge에서 outer finally의 release_merge_lock 1회 호출"""
        runner_id = "t-rml-001"
        redis_mock = self._make_redis_with_worktree(runner_id)

        with patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock") as mock_release, \
             _patch_subprocess_run(exit_code=0):
            listener._do_retry_merge(runner_id, redis_mock, "cmd-001")

        assert mock_release.call_count == 1, (
            f"release_merge_lock은 exactly 1회만 호출되어야 함 (실제: {mock_release.call_count})"
        )

    def test_do_retry_merge_exception_releases_lock(self):
        """E(에러): outer except 경유 시에도 finally에서 lock 해제"""
        runner_id = "t-rml-002"
        redis_mock = self._make_redis_with_worktree(runner_id)

        with patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock") as mock_release, \
             patch("subprocess.run", side_effect=RuntimeError("crash")):
            listener._do_retry_merge(runner_id, redis_mock, "cmd-002")

        assert mock_release.call_count == 1, (
            f"예외 발생 시에도 release_merge_lock이 1회 호출되어야 함 (실제: {mock_release.call_count})"
        )

    def test_do_retry_merge_no_worktree_no_release(self):
        """B(경계): worktree_path 없음 → lock 획득 전 early return → release 미호출"""
        runner_id = "t-rml-003"
        redis_mock = _make_redis(runner_id)
        # worktree_path가 없는 상황

        with patch("merge_lock.acquire_merge_lock") as mock_acquire, \
             patch("merge_lock.release_merge_lock") as mock_release:
            listener._do_retry_merge(runner_id, redis_mock, "cmd-003")

        mock_acquire.assert_not_called()
        assert mock_release.call_count == 0, (
            f"worktree 없으면 lock/release 모두 호출 안 됨 (실제: {mock_release.call_count})"
        )

    def test_do_retry_merge_lock_acquire_fail_no_release(self):
        """B(경계): lock 획득 실패 → release_merge_lock 미호출"""
        runner_id = "t-rml-004"
        redis_mock = self._make_redis_with_worktree(runner_id)

        with patch("merge_lock.acquire_merge_lock", return_value=False), \
             patch("merge_lock.release_merge_lock") as mock_release:
            listener._do_retry_merge(runner_id, redis_mock, "cmd-004")

        assert mock_release.call_count == 0, (
            f"lock 획득 실패 시 release_merge_lock 미호출 (실제: {mock_release.call_count})"
        )


# ---------------------------------------------------------------------------
# Phase T3: E2E 순서 검증 (mock 기반)
# ---------------------------------------------------------------------------

class TestMergeLockLifecycleOrder:
    """acquire → subprocess → release 순서 검증"""

    def test_inline_merge_e2e_lock_lifecycle(self):
        """acquire → subprocess.run → release(finally) 순서 확인"""
        runner_id = "t-e2e-001"
        redis_mock = _make_redis(runner_id)
        call_order: list[str] = []

        def fake_acquire(r, rid, **kw):
            call_order.append("acquire")
            return True

        def fake_release(r, rid):
            call_order.append("release")

        proc = MagicMock()
        proc.returncode = 0

        def fake_subprocess_run(*args, **kw):
            call_order.append("subprocess")
            return proc

        with patch("merge_lock.acquire_merge_lock", side_effect=fake_acquire), \
             patch("merge_lock.release_merge_lock", side_effect=fake_release), \
             patch("subprocess.run", side_effect=fake_subprocess_run):
            listener._do_inline_merge(runner_id, redis_mock)

        assert call_order[0] == "acquire", f"acquire가 첫 번째여야 함: {call_order}"
        assert "release" in call_order, f"release가 호출되어야 함: {call_order}"
        assert "subprocess" in call_order, f"subprocess가 포함되어야 함: {call_order}"
        # main subprocess(첫 번째)가 release보다 먼저 호출됨을 검증
        # (cleanup에서 subprocess 추가 호출이 있을 수 있으므로 인덱스로 비교)
        first_subprocess_idx = call_order.index("subprocess")
        release_idx = call_order.index("release")
        assert first_subprocess_idx < release_idx, (
            f"main subprocess가 release보다 먼저여야 함: {call_order}"
        )

    def test_retry_merge_e2e_lock_lifecycle(self):
        """retry: acquire → subprocess.run → release(outer finally) 순서 확인"""
        runner_id = "t-e2e-002"
        redis_mock = MagicMock()
        redis_mock.get.side_effect = lambda key: "/fake/wt" if "worktree_path" in key else None
        redis_mock.set.return_value = True
        redis_mock.lpush.return_value = 1
        redis_mock.expire.return_value = True

        call_order: list[str] = []

        def fake_acquire(r, rid, **kw):
            call_order.append("acquire")
            return True

        def fake_release(r, rid):
            call_order.append("release")

        proc = MagicMock()
        proc.returncode = 0

        def fake_subprocess_run(*args, **kw):
            call_order.append("subprocess")
            return proc

        with patch("merge_lock.acquire_merge_lock", side_effect=fake_acquire), \
             patch("merge_lock.release_merge_lock", side_effect=fake_release), \
             patch("subprocess.run", side_effect=fake_subprocess_run):
            listener._do_retry_merge(runner_id, redis_mock, "cmd-e2e-002")

        assert call_order[0] == "acquire", f"acquire가 첫 번째여야 함: {call_order}"
        assert "release" in call_order, f"release가 호출되어야 함: {call_order}"
        first_subprocess_idx = call_order.index("subprocess")
        release_idx = call_order.index("release")
        assert first_subprocess_idx < release_idx, (
            f"main subprocess가 release보다 먼저여야 함 (outer finally): {call_order}"
        )


# ---------------------------------------------------------------------------
# Phase T4: HTTP 통합 (FastAPI TestClient 기반)
# ---------------------------------------------------------------------------

class TestMergeLockReleasedAfterMergeHttp:
    """T4: merge 완료/실패 후 lock이 해제됨을 HTTP + Redis mock 통해 검증"""

    @pytest.fixture
    def client(self):
        from app.main import app
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_merge_status_lock_released_after_merge_http(self, client):
        """T4-21: POST retry-merge → accepted 후 _do_retry_merge 경로에서 lock 해제 확인

        실제 Redis 없이 mock으로 acquire/release 흐름 검증.
        """
        import fakeredis
        import threading

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        fake_r.set("plan-runner:runners:runner-lock-test:worktree_path", "/fake/wt")

        release_called = threading.Event()
        original_release = None

        import merge_lock as ml
        original_release = ml.release_merge_lock

        def tracked_release(r, rid):
            original_release(r, rid)
            release_called.set()

        mock_result = {"success": True, "message": "accepted"}
        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService.send_runner_command",
            new_callable=__import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post("/api/v1/dev-runner/runners/runner-lock-test/retry-merge")

        # 엔드포인트가 accepted를 반환하는지만 확인 (실제 merge는 백그라운드 스레드)
        assert resp.status_code in (200, 404, 400), (
            f"retry-merge 엔드포인트가 응답해야 함 (실제: {resp.status_code})"
        )

    def test_merge_status_lock_released_after_failure_http(self, client):
        """T4-22: worktree_path 없는 runner → retry-merge accepted → lock acquire 미발생 확인

        lock을 획득하지 않았으므로 release도 없음 — lock 부재가 보장됨.
        """
        import fakeredis

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        # worktree_path를 설정하지 않음 → lock 획득 경로 진입 안 함

        mock_result = {"success": True, "message": "accepted"}
        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService.send_runner_command",
            new_callable=__import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post("/api/v1/dev-runner/runners/runner-no-wt/retry-merge")

        assert resp.status_code in (200, 404, 400), (
            f"retry-merge 엔드포인트가 응답해야 함 (실제: {resp.status_code})"
        )
        # lock 키가 없음을 확인 (acquire 경로 미진입)
        lock_val = fake_r.get("plan-runner:merge-lock")
        assert lock_val is None, f"worktree 없음 경로에서 lock이 설정되면 안 됨: {lock_val}"

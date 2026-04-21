"""
TC: direct_merge() / _do_direct_merge() — 임시 runner_id, worktree 검증, _do_inline_merge 위임
"""
import json
import sys
import importlib
import importlib.util
import types
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "plan_runner" / "dev-runner-command-listener.py"

_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False

RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
RESULTS_KEY = "plan-runner:command_results"


def _load_listener():
    sys.modules["listener_noise_filter"] = _mock_noise
    spec = importlib.util.spec_from_file_location("_listener_direct", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    mod._running_processes = {}
    mod._running_log_files = {}
    mod._stream_threads = {}
    spec.loader.exec_module(mod)
    return mod


def _get_commands_module():
    return sys.modules["_dr_commands"]


def _get_plan_runner_module():
    return sys.modules["_dr_plan_runner"]


def make_redis_mock():
    redis = MagicMock()
    redis.set.return_value = True
    redis.lpush.return_value = 1
    redis.expire.return_value = True
    redis.sadd.return_value = 1
    redis.get.return_value = "merged"
    return redis


# ---------------------------------------------------------------------------
# _do_direct_merge 단위 테스트
# ---------------------------------------------------------------------------

class TestDoDirectMerge:
    def test_direct_merge_creates_temp_runner_id(self, tmp_path):
        """R(Right): dm- 접두사 runner_id + Redis 키 세팅 + active_runners SADD"""
        cl = _load_listener()
        commands_mod = _get_commands_module()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock()

        with patch.object(commands_mod, "_do_inline_merge") as mock_inline:
            cl._do_direct_merge("runner/abc123", str(worktree), None, redis, "cmd001")

        # active_runners SADD 확인
        sadd_calls = redis.sadd.call_args_list
        assert any(ACTIVE_RUNNERS_KEY in str(c) for c in sadd_calls), "active_runners SADD 없음"

        # dm- 접두사 runner_id 확인
        set_calls = [str(c) for c in redis.set.call_args_list]
        assert any("dm-" in c for c in set_calls), "dm- 접두사 runner_id 없음"

        # _do_inline_merge 호출 + dm- runner_id
        mock_inline.assert_called_once()
        assert mock_inline.call_args[0][0].startswith("dm-"), "임시 runner_id 형식 오류"

    def test_direct_merge_validates_worktree_exists(self, tmp_path):
        """E(Error): 존재하지 않는 worktree_path → 에러 LPUSH + _do_inline_merge 미호출"""
        cl = _load_listener()
        commands_mod = _get_commands_module()

        redis = make_redis_mock()
        non_existent = str(tmp_path / "nonexistent" / "worktree")

        with patch.object(commands_mod, "_do_inline_merge") as mock_inline:
            cl._do_direct_merge("runner/abc123", non_existent, None, redis, "cmd002")

        push_calls = redis.lpush.call_args_list
        assert push_calls, "결과 LPUSH 없음"
        result = json.loads(push_calls[-1][0][1])
        assert result.get("success") is False
        mock_inline.assert_not_called()

    def test_direct_merge_missing_branch_returns_error(self):
        """B(Boundary): branch 미제공 시 즉시 에러 반환 (direct_merge 공개 함수)"""
        cl = _load_listener()

        redis = make_redis_mock()
        command = {"branch": "", "command_id": "cmd003"}

        result = cl.direct_merge(command, redis)

        assert result is not None
        assert result.get("success") is False
        assert "branch required" in result.get("message", "")

    def test_direct_merge_calls_inline_merge(self, tmp_path):
        """R(Right): 유효한 worktree → _do_inline_merge(runner_id, redis) 호출"""
        cl = _load_listener()
        commands_mod = _get_commands_module()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock()

        with patch.object(commands_mod, "_do_inline_merge") as mock_inline:
            cl._do_direct_merge("runner/test001", str(worktree), None, redis, "cmd004")

        mock_inline.assert_called_once()
        args = mock_inline.call_args[0]
        assert args[0].startswith("dm-"), f"첫 번째 인자가 임시 runner_id여야 함: {args[0]}"
        assert args[1] is redis, "두 번째 인자가 redis여야 함"

    def test_direct_merge_refreshes_ownership_snapshot(self, tmp_path):
        """R: direct-merge 임시 runner는 merge 직전에 ownership snapshot을 새로 캡처한다."""
        cl = _load_listener()
        commands_mod = _get_commands_module()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock()

        with patch.object(commands_mod, "_refresh_runner_ownership_snapshot") as mock_refresh, \
             patch.object(commands_mod, "_do_inline_merge"):
            cl._do_direct_merge("runner/snapshot", str(worktree), None, redis, "cmd004b")

        mock_refresh.assert_called_once()
        assert mock_refresh.call_args.kwargs["action"] == "direct-merge"

    def test_direct_merge_sets_minimum_redis_keys(self, tmp_path):
        """R(Right): status/worktree_path/branch/merge_status 키 세팅"""
        cl = _load_listener()
        commands_mod = _get_commands_module()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock()
        branch = "runner/mytest"

        with patch.object(commands_mod, "_do_inline_merge"):
            cl._do_direct_merge(branch, str(worktree), None, redis, "cmd005")

        set_calls = [str(c) for c in redis.set.call_args_list]
        assert any("status" in c and "running" in c for c in set_calls), "status=running 없음"
        assert any("branch" in c and branch in c for c in set_calls), "branch 세팅 없음"
        assert any("worktree_path" in c for c in set_calls), "worktree_path 없음"
        assert any("merge_status" in c and "queued" in c for c in set_calls), "merge_status=queued 없음"

    def test_direct_merge_residue_check_runs_after_subprocess_B(self, tmp_path):
        """B: direct-merge는 residue 차단 메타를 최종 결과에 반영한다."""
        cl = _load_listener()
        commands_mod = _get_commands_module()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock()

        def fake_inline(runner_id, redis_client):
            redis_client.get.side_effect = lambda key: {
                f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status": "residue_blocked",
                f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_message": "post-merge residue detected and restored",
                f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_reason": "residue_guard",
                f"{RUNNER_KEY_PREFIX}:{runner_id}:quarantine_diff_path": "logs/dev_runner/residue/dm.diff",
            }.get(key, "merged")

        with patch.object(commands_mod, "_do_inline_merge", side_effect=fake_inline):
            cl._do_direct_merge("runner/test-residue", str(worktree), None, redis, "cmd-residue")

        push_calls = redis.lpush.call_args_list
        result = json.loads(push_calls[-1][0][1])
        assert result["success"] is False
        assert result["merge_status"] == "residue_blocked"
        assert result["reason"] == "residue_guard"
        assert result["quarantine_diff_path"] == "logs/dev_runner/residue/dm.diff"


# ---------------------------------------------------------------------------
# _do_inline_merge Redis branch 읽기 TC
# ---------------------------------------------------------------------------

class TestInlineMergeBranchFromRedis:
    def _run_inline_merge_with_mock(self, tmp_path, runner_id, branch_value=None):
        """_do_inline_merge 호출 헬퍼 — _execute_merge_with_lock 모킹"""
        import fakeredis
        import sys
        import types
        from unittest.mock import patch, MagicMock

        cl = _load_listener()
        plan_runner_mod = _get_plan_runner_module()

        worktree = tmp_path / f"wt_{runner_id}"
        worktree.mkdir()

        redis = fakeredis.FakeRedis(decode_responses=True)
        redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", str(worktree))
        if branch_value is not None:
            redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", branch_value)
        redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "queued")

        captured = {}

        def mock_execute_merge(runner_id_, redis_client, action_name="inline-merge"):
            captured["branch"] = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id_}:branch")
            return {"success": True, "message": "mocked", "merge_status": "merged", "action": action_name}

        import _dr_stream_cleanup as stream_cleanup_mod
        with patch.object(stream_cleanup_mod, "_execute_merge_with_lock", side_effect=mock_execute_merge):
            with patch.object(stream_cleanup_mod, "_cleanup_process_state", MagicMock()):
                cl._do_inline_merge(runner_id, redis)

        return captured

    def test_inline_merge_reads_branch_from_redis(self, tmp_path):
        """R(Right): Redis에 {runner_id}:branch 세팅 후 workflow.run(branch=...) 전달 확인"""
        captured = self._run_inline_merge_with_mock(tmp_path, "dm-testbranch", branch_value="plan/test-plan")
        assert captured.get("branch") == "plan/test-plan", f"branch 전달 오류: {captured}"

    def test_inline_merge_branch_none_when_redis_missing(self, tmp_path):
        """E(Error/Boundary): Redis에 branch 키 없을 때 workflow.run(branch=None) 전달"""
        captured = self._run_inline_merge_with_mock(tmp_path, "dm-nobranch", branch_value=None)
        assert captured.get("branch") is None, f"branch가 None이어야 함: {captured}"


# ---------------------------------------------------------------------------
# API executor_service 단위 테스트
# ---------------------------------------------------------------------------

class TestDirectMergeEndpoint:
    @pytest.mark.asyncio
    async def test_direct_merge_endpoint_sends_command(self):
        """R(Right): send_direct_merge_command → Redis에 action=direct-merge + branch 전송"""
        from app.modules.dev_runner.services.executor_service import ExecutorService

        from app.modules.dev_runner.services.merge_service import MergeService

        svc = ExecutorService.__new__(ExecutorService)
        svc.async_redis = AsyncMock()
        svc.async_redis.ping = AsyncMock(return_value=True)

        captured_command = {}

        async def fake_lpush(key, value):
            captured_command.update(json.loads(value))
            return 1

        async def fake_brpop(key, timeout=None):
            result = {"success": True, "message": "accepted", "action": "direct-merge"}
            return (key, json.dumps(result).encode())

        svc.async_redis.lpush = fake_lpush
        svc.async_redis.brpop = fake_brpop
        svc.async_redis.delete = AsyncMock()

        # __new__로 생성 시 self.merge가 없으므로 직접 초기화
        svc.merge = MergeService(svc.async_redis, lambda rid, sfx: f"plan-runner:runners:{rid}:{sfx}", svc._send_command if hasattr(svc, "_send_command") else None)
        # _send_command가 없으므로 직접 등록 (lpush/brpop 기반)
        from app.modules.dev_runner.services.redis_connection import COMMANDS_KEY, RESULTS_KEY, COMMAND_TIMEOUT
        async def _send_command(command, timeout=COMMAND_TIMEOUT):
            import uuid
            command["command_id"] = command.get("command_id", str(uuid.uuid4()))
            await svc.async_redis.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))
            raw = await svc.async_redis.brpop(f"{RESULTS_KEY}:{command['command_id']}", timeout=timeout)
            if raw is None:
                return None
            return json.loads(raw[1])
        svc._send_command = _send_command
        svc.merge = MergeService(svc.async_redis, lambda rid, sfx: f"plan-runner:runners:{rid}:{sfx}", _send_command)

        await svc.send_direct_merge_command("runner/test123", "/worktree/path", None)

        assert captured_command.get("action") == "direct-merge"
        assert captured_command.get("branch") == "runner/test123"
        assert "command_id" in captured_command


# ---------------------------------------------------------------------------
# _pub() Redis list 이중 기록 TC
# ---------------------------------------------------------------------------

class TestPubWritesToLogList:
    def test_pub_writes_to_log_list_R(self):
        """R(Right): _pub_and_log() 호출 시 redis.rpush(log_list_key, ...) 호출 확인"""
        cl = _load_listener()
        redis = make_redis_mock()
        runner_id = "t-dmerge-test123"

        # _pub_and_log를 직접 호출하여 rpush가 log_list_key로 발생하는지 검증
        # (_pub 클로저는 _execute_merge_with_lock 내부에 있어 외부에서 직접 접근 불가)
        cl._pub_and_log(runner_id, "test log message", redis, "MERGE")

        # rpush가 log_list_key로 호출되었는지 확인
        rpush_calls = redis.rpush.call_args_list
        log_list_key = f"plan-runner:logs:list:{runner_id}"
        assert any(log_list_key in str(c) for c in rpush_calls), \
            f"rpush({log_list_key}, ...) 호출 없음. calls: {rpush_calls}"

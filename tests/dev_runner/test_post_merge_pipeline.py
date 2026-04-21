"""
TC: _do_inline_merge / _do_retry_merge subprocess 援먯껜 ?⑥쐞 ?뚯뒪??

Phase T1: plan-runner post-merge subprocess ?몄텧 ?⑦꽩 寃利?
- 12. test_do_inline_merge_calls_plan_runner_subprocess_R
- 13. test_do_inline_merge_subprocess_exit0_sets_merged_R
- 14. test_do_inline_merge_subprocess_exit1_sets_error_E
- 15. test_do_inline_merge_subprocess_exit3_sets_conflict_B
- 16. test_do_inline_merge_cleanup_always_runs_R
- 17. test_do_inline_merge_no_restart_after_merge_B
- 18. test_do_retry_merge_calls_plan_runner_subprocess_R
- 19. test_deleted_functions_not_exist_R
"""
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import fakeredis
import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_PLAN_RUNNER_DIR = _SCRIPTS_DIR / "plan_runner"
if str(_PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_PLAN_RUNNER_DIR))

_SCRIPT_PATH = _PLAN_RUNNER_DIR / "dev-runner-command-listener.py"
_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False

RUNNER_KEY_PREFIX = "plan-runner:runners"


def _load_listener():
    sys.modules["listener_noise_filter"] = _mock_noise
    spec = importlib.util.spec_from_file_location("_listener_pmp", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    mod._running_processes = {}
    mod._running_log_files = {}
    mod._stream_threads = {}
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cl():
    return _load_listener()


@pytest.fixture(scope="module")
def dr_merge_mod(cl):  # noqa: F811 ??cl 濡쒕뱶 ??_dr_merge媛 sys.modules???깅줉??
    """_dr_merge 紐⑤뱢 李몄“. _execute_merge_with_lock ?대??먯꽌 吏곸젒 李몄“?섎뒗 紐⑤뱢."""
    return sys.modules["_dr_merge"]


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


def _make_redis_mock(worktree_path=None, plan_file=None, branch=None):
    redis = MagicMock()

    def redis_get(key):
        if "worktree_path" in key:
            return str(worktree_path) if worktree_path else None
        if "plan_file" in key:
            return plan_file
        if "branch" in key:
            return branch
        if "merge_requested" in key:
            return "1"
        return None

    redis.get.side_effect = redis_get
    redis.set = MagicMock()
    redis.delete = MagicMock()
    redis.publish = MagicMock()
    redis.lrange = MagicMock(return_value=[])
    redis.lpush = MagicMock()
    redis.expire = MagicMock()
    redis.srem = MagicMock()
    redis.smembers = MagicMock(return_value=set())
    return redis


def _merge_lock_patch():
    """merge_queue 紐⑤뱢 ?꾩껜瑜?mock (acquire?뭈rue, release?묿one)"""
    mock_lock_mod = types.ModuleType("merge_queue")
    mock_lock_mod.acquire_merge_turn = MagicMock(return_value=True)
    mock_lock_mod.release_merge_turn = MagicMock()
    mock_lock_mod._get_repo_id = MagicMock(return_value="repo-test")
    return patch.dict("sys.modules", {"merge_queue": mock_lock_mod})


# ?? Phase T1: subprocess 援먯껜 ?⑦꽩 TC ????????????????????????????????????????

class TestDoInlineMergeSubprocess:
    def test_do_inline_merge_calls_plan_runner_subprocess_R(self, cl, tmp_path):
        """R(Right): _do_inline_merge ?몄텧 ??subprocess.run??
        [..PLAN_RUNNER_PYTHON, '-m', 'plan_runner', 'post-merge', '--runner-id', ...] 紐낅졊?쇰줈 ?몄텧??"""
        redis = _make_redis_mock()
        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result) as mock_run:
            cl._do_inline_merge("r1", redis)

        post_merge_calls = [
            c for c in mock_run.call_args_list
            if "plan_runner" in str(c) and "post-merge" in str(c)
        ]
        assert len(post_merge_calls) >= 1, f"plan_runner post-merge ?몄텧???놁쓬: {mock_run.call_args_list}"
        cmd = post_merge_calls[0][0][0]
        assert "-m" in cmd
        assert "plan_runner" in cmd
        assert "post-merge" in cmd
        assert "--runner-id" in cmd
        assert "r1" in cmd

    def test_do_inline_merge_subprocess_exit0_sets_merged_R(self, cl, tmp_path):
        """R(Right): subprocess returncode=0 ??merge_status='merged' ?ㅼ젙"""
        redis = _make_redis_mock()
        set_calls = []
        redis.set.side_effect = lambda k, v: set_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_inline_merge("r_exit0", redis)

        status_values = [v for k, v in set_calls if "merge_status" in k]
        assert "merged" in status_values

    def test_do_inline_merge_subprocess_exit1_sets_error_E(self, cl, tmp_path):
        """E(Error): subprocess returncode=1 ??merge_status='error' ?ㅼ젙"""
        redis = _make_redis_mock()
        set_calls = []
        redis.set.side_effect = lambda k, v: set_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 1

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("_dr_merge._launch_general_merge_resolver_process", return_value={"success": False, "message": "fail"}), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_inline_merge("r_exit1", redis)

        status_values = [v for k, v in set_calls if "merge_status" in k]
        assert "error" in status_values
        assert "merged" not in status_values

    def test_do_inline_merge_subprocess_exit3_sets_conflict_B(self, cl, tmp_path):
        """B(Boundary): subprocess returncode=3 ??merge_status='conflict' ?ㅼ젙"""
        redis = _make_redis_mock()
        set_calls = []
        redis.set.side_effect = lambda k, v: set_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 3

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result), \
             patch("_dr_merge._launch_conflict_resolver_process",
                   return_value={"success": False, "message": "mocked"}):
            cl._do_inline_merge("r_exit3", redis)

        status_values = [v for k, v in set_calls if "merge_status" in k]
        assert "conflict" in status_values

    def test_do_inline_merge_cleanup_always_runs_R(self, cl, tmp_path):
        """R(Right): subprocess ?깃났/?ㅽ뙣 紐⑤몢 _cleanup_process_state ?몄텧??"""
        # ?깃났 耳?댁뒪
        redis_ok = _make_redis_mock()
        proc_ok = MagicMock()
        proc_ok.returncode = 0

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state") as mock_cleanup_ok, \
             patch("subprocess.run", return_value=proc_ok):
            cl._do_inline_merge("r_cleanup_ok", redis_ok)

        mock_cleanup_ok.assert_called_once()

        # ?ㅽ뙣 耳?댁뒪
        redis_fail = _make_redis_mock()
        proc_fail = MagicMock()
        proc_fail.returncode = 1

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state") as mock_cleanup_fail, \
             patch("subprocess.run", return_value=proc_fail), \
             patch("_dr_merge._launch_general_merge_resolver_process",
                   return_value={"success": False, "message": "mocked"}):
            cl._do_inline_merge("r_cleanup_fail", redis_fail)

        mock_cleanup_fail.assert_called_once()

    def test_do_inline_merge_no_restart_after_merge_B(self, cl, tmp_path):
        """B(Boundary): restart_after_merge Redis ?ㅺ? ?ㅼ젙?섏? ?딆쓬"""
        redis = _make_redis_mock()
        set_keys = []
        redis.set.side_effect = lambda k, v: set_keys.append(k)

        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_inline_merge("r_no_restart", redis)

        assert not any("restart_after_merge" in k for k in set_keys)

    def test_do_inline_merge_merge_results_pushed_R(self, cl, tmp_path):
        """R(Right): ?꾨즺 ??plan-runner:merge-results??寃곌낵 push"""
        redis = _make_redis_mock()
        lpush_calls = []
        redis.lpush.side_effect = lambda k, v: lpush_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_inline_merge("r_results", redis)

        pushed_keys = [k for k, v in lpush_calls]
        assert "plan-runner:merge-results" in pushed_keys

    def test_do_inline_merge_subprocess_exit0_emits_merge_completed_sentinel_R(self, cl, tmp_path):
        """R(Right): _do_inline_merge 성공 시 merge-log completed sentinel이 1회 publish된다."""
        redis = _make_redis_mock()
        publish_calls = []
        redis.publish.side_effect = lambda channel, payload: publish_calls.append((channel, payload))

        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result):
            result = cl._do_inline_merge("r_inline_ok", redis)

        assert result is None
        merge_publish_calls = [
            c for c in publish_calls
            if c[0] == "plan-runner:merge-log:r_inline_ok"
        ]
        assert merge_publish_calls == [
            ("plan-runner:merge-log:r_inline_ok", "__MERGE_COMPLETED__")
        ]

    def test_do_inline_merge_subprocess_exit3_emits_merge_failed_sentinel_B(self, cl, tmp_path):
        """B(Boundary): _do_inline_merge conflict 시 merge-log merge_failed sentinel이 1회 publish된다."""
        redis = _make_redis_mock()
        publish_calls = []
        redis.publish.side_effect = lambda channel, payload: publish_calls.append((channel, payload))

        proc_result = MagicMock()
        proc_result.returncode = 3

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result), \
             patch("_dr_merge._launch_conflict_resolver_process",
                   return_value={"success": False, "message": "mocked"}):
            cl._do_inline_merge("r_inline_fail", redis)

        merge_publish_calls = [
            c for c in publish_calls
            if c[0] == "plan-runner:merge-log:r_inline_fail"
        ]
        assert merge_publish_calls == [
            ("plan-runner:merge-log:r_inline_fail", "__MERGE_COMPLETED::merge_failed__")
        ]


class TestMergeCompletedSentinelEmission:
    def test_build_merge_completed_sentinel_success_R(self, dr_merge_mod):
        """R: 성공 결과는 __MERGE_COMPLETED__로 정규화된다."""
        sentinel = dr_merge_mod._build_merge_completed_sentinel({"success": True, "merge_status": "merged"})
        assert sentinel == "__MERGE_COMPLETED__"

    def test_build_merge_completed_sentinel_failure_B(self, dr_merge_mod):
        """B: 실패 결과는 __MERGE_COMPLETED::merge_failed__로 정규화된다."""
        sentinel = dr_merge_mod._build_merge_completed_sentinel({"success": False, "merge_status": "conflict"})
        assert sentinel == "__MERGE_COMPLETED::merge_failed__"

    def test_publish_merge_completed_sentinel_success_to_merge_log_only_R(self, dr_merge_mod):
        """R: terminal success sentinel은 merge-log 채널에만 publish된다."""
        redis = _make_redis_mock()

        dr_merge_mod._publish_merge_completed_sentinel(
            "r_merge_ok",
            redis,
            {"success": True, "merge_status": "merged"},
        )

        redis.publish.assert_called_once_with(
            "plan-runner:merge-log:r_merge_ok",
            "__MERGE_COMPLETED__",
        )

    def test_publish_merge_completed_sentinel_failure_to_merge_log_only_B(self, dr_merge_mod):
        """B: terminal failure sentinel은 merge-log 채널에만 publish된다."""
        redis = _make_redis_mock()

        dr_merge_mod._publish_merge_completed_sentinel(
            "r_merge_fail",
            redis,
            {"success": False, "merge_status": "conflict"},
        )

        redis.publish.assert_called_once_with(
            "plan-runner:merge-log:r_merge_fail",
            "__MERGE_COMPLETED::merge_failed__",
        )

    def test_execute_merge_with_lock_publishes_success_merge_completed_sentinel_R(self, cl, tmp_path):
        """R: _execute_merge_with_lock 성공 경로에서 merge-log completed sentinel이 1회 publish된다."""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file=None, branch=None)
        publish_calls = []
        redis.publish.side_effect = lambda channel, payload: publish_calls.append((channel, payload))
        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result):
            result = cl._execute_merge_with_lock("r_merge_ok", redis)

        assert result["success"] is True
        merge_publish_calls = [
            c for c in publish_calls
            if c[0] == "plan-runner:merge-log:r_merge_ok"
        ]
        assert merge_publish_calls == [
            ("plan-runner:merge-log:r_merge_ok", "__MERGE_COMPLETED__")
        ]

    def test_execute_merge_with_lock_publishes_failure_merge_completed_sentinel_B(self, cl, tmp_path):
        """B: _execute_merge_with_lock 실패 경로에서 merge-log merge_failed sentinel이 1회 publish된다."""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file=None, branch=None)
        publish_calls = []
        redis.publish.side_effect = lambda channel, payload: publish_calls.append((channel, payload))
        proc_result = MagicMock()
        proc_result.returncode = 3

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch("_dr_merge._launch_conflict_resolver_process", return_value={"success": False, "message": "mocked"}):
            result = cl._execute_merge_with_lock("r_merge_fail", redis)

        assert result["success"] is False
        assert result["merge_status"] == "conflict"
        merge_publish_calls = [
            c for c in publish_calls
            if c[0] == "plan-runner:merge-log:r_merge_fail"
        ]
        assert merge_publish_calls == [
            ("plan-runner:merge-log:r_merge_fail", "__MERGE_COMPLETED::merge_failed__")
        ]

    def test_execute_merge_with_lock_retry_action_emits_merge_completed_sentinel_R(self, cl, tmp_path):
        """R(Right): retry-merge action도 동일한 merge-log completed sentinel 계약을 공유한다."""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file=None, branch=None)
        publish_calls = []
        redis.publish.side_effect = lambda channel, payload: publish_calls.append((channel, payload))
        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result):
            result = cl._execute_merge_with_lock("r_retry_ok", redis, action_name="retry-merge")

        assert result["success"] is True
        assert result["action"] == "retry-merge"
        merge_publish_calls = [
            c for c in publish_calls
            if c[0] == "plan-runner:merge-log:r_retry_ok"
        ]
        assert merge_publish_calls == [
            ("plan-runner:merge-log:r_retry_ok", "__MERGE_COMPLETED__")
        ]


class TestDoRetryMergeSubprocess:
    def test_do_retry_merge_calls_plan_runner_subprocess_R(self, cl, tmp_path):
        """R(Right): _do_retry_merge ?몄텧 ??subprocess.run??post-merge 紐낅졊?쇰줈 ?몄텧??"""
        redis = _make_redis_mock(worktree_path=tmp_path)
        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("_dr_commands._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result) as mock_run:
            cl._do_retry_merge("r_retry", redis, "cmd123")

        mock_run.assert_called()
        # subprocess.run??git rev-parse, worktree remove ???대? ?몄텧???덉쑝誘濡?
        # plan_runner + post-merge ?몄옄瑜?紐⑤몢 ?ы븿???몄텧留??꾪꽣
        post_merge_calls = [
            c for c in mock_run.call_args_list
            if "plan_runner" in str(c) and "post-merge" in str(c)
        ]
        assert len(post_merge_calls) >= 1, f"plan_runner post-merge ?몄텧???놁쓬: {mock_run.call_args_list}"
        cmd = post_merge_calls[0][0][0]
        assert "--runner-id" in cmd
        assert "r_retry" in cmd

    def test_do_retry_merge_exit0_success_result_R(self, cl, tmp_path):
        """R(Right): exit_code=0 ??result.success=True + merge-results push"""
        redis = _make_redis_mock(worktree_path=tmp_path)
        lpush_calls = []
        redis.lpush.side_effect = lambda k, v: lpush_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("_dr_commands._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_retry_merge("r_retry_ok", redis, "cmd_ok")

        # result_key??push??寃곌낵 ?뺤씤
        result_key = f"{cl.RESULTS_KEY}:cmd_ok"
        result_pushes = [v for k, v in lpush_calls if k == result_key]
        assert len(result_pushes) > 0
        result_data = json.loads(result_pushes[-1])
        assert result_data.get("success") is True

    def test_do_retry_merge_exit3_conflict_result_B(self, cl, tmp_path):
        """B(Boundary): exit_code=3 ??result.conflict=True"""
        redis = _make_redis_mock(worktree_path=tmp_path)
        lpush_calls = []
        redis.lpush.side_effect = lambda k, v: lpush_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 3

        with _merge_lock_patch(), \
             patch("_dr_commands._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result), \
             patch("_dr_merge._launch_conflict_resolver_process",
                   return_value={"success": False, "message": "mocked"}):
            cl._do_retry_merge("r_retry_conflict", redis, "cmd_conflict")

        result_key = f"{cl.RESULTS_KEY}:cmd_conflict"
        result_pushes = [v for k, v in lpush_calls if k == result_key]
        assert len(result_pushes) > 0
        result_data = json.loads(result_pushes[-1])
        assert result_data.get("conflict") is True


class TestCleanupNoPopenCreated:
    def test_cleanup_runs_R_no_popen_created(self, cl):
        """T3-?뚭?: launcher mock??Popen ?앹꽦??李⑤떒?섎뒗吏 寃利?

        _do_inline_merge ?ㅽ뙣 耳?댁뒪(returncode=1)?먯꽌
        _launch_general_merge_resolver_process瑜?mock?섎㈃
        subprocess.Popen???ㅼ젣濡??몄텧?섏? ?딆븘???쒕떎.

        ??TC媛 ?ㅽ뙣(Popen.call_count > 0)?섎㈃ launcher mock???놁뼱??
        ?ㅼ젣 ?꾨줈?몄뒪媛 ?앹꽦?섍퀬 ?덈떎???섎? ??timeout ?щ컻 寃쎈낫.
        """
        redis_fail = _make_redis_mock()
        proc_fail = MagicMock()
        proc_fail.returncode = 1

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_fail), \
             patch("_dr_merge._launch_general_merge_resolver_process",
                   return_value={"success": False, "message": "mocked"}) as mock_launcher, \
             patch("subprocess.Popen") as mock_popen:
            cl._do_inline_merge("r_no_popen", redis_fail)

        # launcher mock???곸슜?섏뼱 Popen???몄텧?섏? ?딆븘????
        assert mock_popen.call_count == 0, (
            f"subprocess.Popen??{mock_popen.call_count}???몄텧????"
            "_launch_general_merge_resolver_process mock??Popen 李⑤떒???ㅽ뙣?덇굅??"
            "launcher mock ?놁씠 ?ㅼ젣 ?꾨줈?몄뒪媛 ?앹꽦?섍퀬 ?덉쓬 (timeout ?щ컻 ?꾪뿕)"
        )
        # launcher mock? ?뺥솗??1???몄텧?섏뼱????
        mock_launcher.assert_called_once()


class TestDeletedFunctions:
    def test_deleted_functions_not_exist_R(self, cl):
        """R(Right): _post_merge_pipeline, _restart_plan_runner_after_merge,
        _resolve_todo_file媛 紐⑤뱢 ?띿꽦???놁쓬"""
        assert not hasattr(cl, "_post_merge_pipeline"), \
            "_post_merge_pipeline should be deleted (replaced by plan-runner post-merge)"
        assert not hasattr(cl, "_restart_plan_runner_after_merge"), \
            "_restart_plan_runner_after_merge should be deleted"
        assert not hasattr(cl, "_resolve_todo_file"), \
            "_resolve_todo_file should be deleted"


# ?? Phase T3: E2E ?뚯뒪????????????????????????????????????????????????????????

class TestInlineMergeE2ESubprocessFlow:
    def test_inline_merge_e2e_subprocess_flow(self, cl):
        """T3-E2E: _do_inline_merge ?꾩껜 ?먮쫫 ??subprocess mock ??exit_code=0
        ??merge_status='merged' ??merge-results push ??_cleanup_process_state ?몄텧 ?뺤씤
        """
        import fakeredis as _fakeredis
        import types as _types

        fake_r = _fakeredis.FakeRedis(decode_responses=True)
        runner_id = "e2e-inline-01"
        prefix = cl.RUNNER_KEY_PREFIX

        # per-runner ???ъ쟾 ?ㅼ젙
        fake_r.set(f"{prefix}:{runner_id}:merge_requested", "1")
        fake_r.set(f"{prefix}:{runner_id}:plan_file", "docs/plan/test.md")
        fake_r.set(f"{prefix}:{runner_id}:branch", "impl/test")
        fake_r.set(f"{prefix}:{runner_id}:worktree_path", "D:/tmp/wt")

        mock_lock_mod = _types.ModuleType("merge_queue")
        mock_lock_mod.acquire_merge_turn = MagicMock(return_value=True)
        mock_lock_mod.release_merge_turn = MagicMock()
        mock_lock_mod._get_repo_id = MagicMock(return_value="repo-test")

        proc_result = MagicMock()
        proc_result.returncode = 0

        with patch.dict("sys.modules", {"merge_queue": mock_lock_mod}), \
             patch("subprocess.run", return_value=proc_result), \
             patch("_dr_stream_cleanup._cleanup_process_state") as mock_cleanup:
            cl._do_inline_merge(runner_id, fake_r)

        # merge_status = "merged" ?뺤씤
        assert fake_r.get(f"{prefix}:{runner_id}:merge_status") == "merged"

        # merge-results push ?뺤씤
        results = fake_r.lrange("plan-runner:merge-results", 0, 0)
        assert len(results) > 0
        result_data = json.loads(results[0])
        assert result_data["runner_id"] == runner_id
        assert result_data["success"] is True

        # _cleanup_process_state ?몄텧 ?뺤씤
        mock_cleanup.assert_called_once()

    def test_retry_merge_e2e_subprocess_flow(self, cl):
        """T3-E2E: _do_retry_merge ?꾩껜 ?먮쫫 ??subprocess mock ??exit_code=0
        ??merge_status='merged' ??merge-results push ??_cleanup_process_state ?몄텧 ?뺤씤
        _do_inline_merge? ?숈씪 ?⑦꽩?댁?留?吏꾩엯 寃쎈줈媛 ?ㅻⅤ誘濡?蹂꾨룄 寃利?
        """
        import fakeredis as _fakeredis
        import types as _types

        fake_r = _fakeredis.FakeRedis(decode_responses=True)
        runner_id = "e2e-retry-01"
        prefix = cl.RUNNER_KEY_PREFIX

        fake_r.set(f"{prefix}:{runner_id}:worktree_path", "D:/tmp/wt_retry")
        fake_r.set(f"{prefix}:{runner_id}:plan_file", "docs/plan/test.md")
        fake_r.set(f"{prefix}:{runner_id}:branch", "impl/test")

        mock_lock_mod = _types.ModuleType("merge_queue")
        mock_lock_mod.acquire_merge_turn = MagicMock(return_value=True)
        mock_lock_mod.release_merge_turn = MagicMock()
        mock_lock_mod._get_repo_id = MagicMock(return_value="repo-test")

        proc_result = MagicMock()
        proc_result.returncode = 0

        with patch.dict("sys.modules", {"merge_queue": mock_lock_mod}), \
             patch("subprocess.run", return_value=proc_result), \
             patch("_dr_commands._cleanup_process_state") as mock_cleanup:
            cl._do_retry_merge(runner_id, fake_r, "cmd_e2e")

        # merge_status = "merged" ?뺤씤
        assert fake_r.get(f"{prefix}:{runner_id}:merge_status") == "merged"

        # merge-results push ?뺤씤
        results = fake_r.lrange("plan-runner:merge-results", 0, 0)
        assert len(results) > 0
        result_data = json.loads(results[0])
        assert result_data["runner_id"] == runner_id
        assert result_data["success"] is True

        # _cleanup_process_state ?몄텧 ?뺤씤
        mock_cleanup.assert_called_once()

        # result_key??push??寃곌낵 ?뺤씤
        result_key = f"{cl.RESULTS_KEY}:cmd_e2e"
        pushed = fake_r.lrange(result_key, 0, 0)
        assert len(pushed) > 0
        pushed_data = json.loads(pushed[0])
        assert pushed_data["success"] is True

    def test_execute_merge_with_lock_residue_blocked_persists_quarantine_T3(self, cl, dr_merge_mod):
        """T3: residue helper 실패 시 result/Redis/merge-results가 residue_blocked로 고정된다."""
        import fakeredis as _fakeredis
        import types as _types

        fake_r = _fakeredis.FakeRedis(decode_responses=True)
        runner_id = "e2e-residue-01"
        prefix = cl.RUNNER_KEY_PREFIX

        fake_r.set(f"{prefix}:{runner_id}:worktree_path", "D:/tmp/wt_residue")
        fake_r.set(f"{prefix}:{runner_id}:plan_file", "docs/plan/test.md")
        fake_r.set(f"{prefix}:{runner_id}:branch", "impl/test")

        mock_lock_mod = _types.ModuleType("merge_queue")
        mock_lock_mod.acquire_merge_turn = MagicMock(return_value=True)
        mock_lock_mod.release_merge_turn = MagicMock()
        mock_lock_mod._get_repo_id = MagicMock(return_value="repo-test")

        proc_result = MagicMock()
        proc_result.returncode = 0

        residue_result = {
            "success": False,
            "status": "residue_blocked",
            "reason": "residue_guard",
            "message": "post-merge residue detected and restored",
            "quarantine_diff_path": "logs/dev_runner/residue/e2e-residue-01.diff",
        }

        with patch.dict("sys.modules", {"merge_queue": mock_lock_mod}), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(dr_merge_mod, "_check_post_merge_residue", return_value=residue_result):
            result = cl._execute_merge_with_lock(runner_id, fake_r)

        assert result["success"] is False
        assert result["merge_status"] == "residue_blocked"
        assert result["reason"] == "residue_guard"
        assert result["quarantine_diff_path"].endswith("e2e-residue-01.diff")
        assert fake_r.get(f"{prefix}:{runner_id}:merge_status") == "residue_blocked"
        assert fake_r.get(f"{prefix}:{runner_id}:done_post_merge_status") == "skipped_residue"
        assert fake_r.get(f"{prefix}:{runner_id}:done_post_merge_error") == "residue_guard"
        assert fake_r.get(f"{prefix}:{runner_id}:quarantine_diff_path").endswith("e2e-residue-01.diff")

        results = fake_r.lrange("plan-runner:merge-results", 0, 0)
        assert len(results) > 0
        result_data = json.loads(results[0])
        assert result_data["runner_id"] == runner_id
        assert result_data["status"] == "failed"
        assert result_data["success"] is False
        assert result_data["reason"] == "residue_guard"


# ?? Phase T1 (exit_code=2): auto-impl-post-merge ?먮룞 蹂듦뎄 TC ?????????????????

class TestExitCode2AutoImplPostMerge:
    def test_exit_code_2_triggers_auto_impl_post_merge_R(self, cl, dr_merge_mod, tmp_path):
        """R(Right): exit_code=2 ??_launch_auto_impl_post_merge_process ?몄텧??"""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file="docs/plan/test.md")
        proc_result = MagicMock()
        proc_result.returncode = 2

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(dr_merge_mod, "_launch_auto_impl_post_merge_process", return_value={"success": False, "message": "fail"}) as mock_fix:
            cl._execute_merge_with_lock("r_exit2", redis)

        mock_fix.assert_called_once()
        call_kwargs = mock_fix.call_args
        assert call_kwargs[1].get("runner_id") == "r_exit2" or call_kwargs[0][0] == "r_exit2"

    def test_exit_code_2_success_after_fix_calls_post_merge_done_R(self, cl, dr_merge_mod, tmp_path):
        """R(Right): _launch_auto_impl_post_merge_process ??success=True ??_handle_post_merge_done ?몄텧 + merge_status='merged'"""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file="docs/plan/test.md")
        proc_result = MagicMock()
        proc_result.returncode = 2

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(dr_merge_mod, "_launch_auto_impl_post_merge_process", return_value={"success": True, "message": "ok"}), \
             patch.object(dr_merge_mod, "_handle_post_merge_done") as mock_done:
            result = cl._execute_merge_with_lock("r_exit2_ok", redis)

        assert result["success"] is True
        assert result["merge_status"] == "merged"
        mock_done.assert_called_once()

    def test_exit_code_2_no_plan_file_skips_auto_fix_B(self, cl, dr_merge_mod, tmp_path):
        """B(Boundary): plan_file=None ??_launch_auto_impl_post_merge_process ?몄텧 ?놁씠 merge_status='test_failed'"""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file=None)
        proc_result = MagicMock()
        proc_result.returncode = 2

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(dr_merge_mod, "_launch_auto_impl_post_merge_process") as mock_fix:
            result = cl._execute_merge_with_lock("r_exit2_noplan", redis)

        mock_fix.assert_not_called()
        assert result["success"] is False
        assert result["merge_status"] == "test_failed"

    def test_exit_code_2_fix_failure_sets_test_failed_status_E(self, cl, dr_merge_mod, tmp_path):
        """E(Error): _launch_auto_impl_post_merge_process ??success=False ??merge_status='test_failed'"""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file="docs/plan/test.md")
        proc_result = MagicMock()
        proc_result.returncode = 2

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(dr_merge_mod, "_launch_auto_impl_post_merge_process", return_value={"success": False, "message": "fix failed"}):
            result = cl._execute_merge_with_lock("r_exit2_fail", redis)

        assert result["success"] is False
        assert result["merge_status"] == "test_failed"

    def test_exit_code_2_retry_limit_prevents_infinite_loop_B(self, cl, dr_merge_mod, tmp_path):
        """B(Boundary): _test_fix_attempt=2 ??_launch_auto_impl_post_merge_process ?몄텧 ?놁씠 利됱떆 test_failed"""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file="docs/plan/test.md")
        proc_result = MagicMock()
        proc_result.returncode = 2

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(dr_merge_mod, "_launch_auto_impl_post_merge_process") as mock_fix:
            result = cl._execute_merge_with_lock("r_exit2_limit", redis, _test_fix_attempt=2)

        mock_fix.assert_not_called()
        assert result["success"] is False
        assert result["merge_status"] == "test_failed"

    def test_exit_code_2_merge_status_transitions_Co(self, cl, dr_merge_mod, tmp_path):
        """Co(Conformance): exit_code=2 泥섎━ 以?merge_status ?꾩씠: merging ??fixing ??test_failed(?ㅽ뙣 ??"""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file="docs/plan/test.md")
        proc_result = MagicMock()
        proc_result.returncode = 2
        set_calls = []
        redis.set.side_effect = lambda k, v: set_calls.append((k, v))

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(dr_merge_mod, "_launch_auto_impl_post_merge_process", return_value={"success": False, "message": "fail"}):
            cl._execute_merge_with_lock("r_co", redis)

        merge_status_calls = [(k, v) for k, v in set_calls if "merge_status" in k]
        statuses = [v for _, v in merge_status_calls]
        assert "merging" in statuses
        assert "fixing" in statuses
        assert "test_failed" in statuses
        # ?쒖꽌 寃利? merging ??fixing ??test_failed
        idx_merging = next(i for i, v in enumerate(statuses) if v == "merging")
        idx_fixing = next(i for i, v in enumerate(statuses) if v == "fixing")
        idx_failed = next(i for i, v in enumerate(statuses) if v == "test_failed")
        assert idx_merging < idx_fixing < idx_failed


# ?? Phase T3 (exit_code=2): fakeredis ?듯빀 TC ?????????????????????????????????

class TestExitCode2IntegrationFakeRedis:
    def test_exit_code_2_integration_with_fakeredis(self, cl, dr_merge_mod):
        """T3(?듯빀): fakeredis濡?_execute_merge_with_lock exit_code=2 ?쒕굹由ъ삤 寃利?

        Redis merge_status ?꾩씠: merging ??fixing ??test_failed
        """
        import fakeredis as _fakeredis
        import types as _types

        fake_r = _fakeredis.FakeRedis(decode_responses=True)
        runner_id = "e2e-exit2-01"
        prefix = cl.RUNNER_KEY_PREFIX

        fake_r.set(f"{prefix}:{runner_id}:worktree_path", "D:/tmp/wt_exit2")
        fake_r.set(f"{prefix}:{runner_id}:plan_file", "docs/plan/test.md")
        fake_r.set(f"{prefix}:{runner_id}:branch", "impl/test")

        mock_lock_mod = _types.ModuleType("merge_queue")
        mock_lock_mod.acquire_merge_turn = MagicMock(return_value=True)
        mock_lock_mod.release_merge_turn = MagicMock()
        mock_lock_mod._get_repo_id = MagicMock(return_value="repo-test")

        proc_result = MagicMock()
        proc_result.returncode = 2

        with patch.dict("sys.modules", {"merge_queue": mock_lock_mod}), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(dr_merge_mod, "_launch_auto_impl_post_merge_process", return_value={"success": False, "message": "fail"}):
            result = cl._execute_merge_with_lock(runner_id, fake_r)

        # 理쒖쥌 merge_status = "test_failed"
        assert fake_r.get(f"{prefix}:{runner_id}:merge_status") == "test_failed"
        assert result["success"] is False
        assert result["merge_status"] == "test_failed"

        # merge-results push ?뺤씤
        results = fake_r.lrange("plan-runner:merge-results", 0, 0)
        assert len(results) > 0
        result_data = json.loads(results[0])
        assert result_data["runner_id"] == runner_id
        assert result_data["success"] is False



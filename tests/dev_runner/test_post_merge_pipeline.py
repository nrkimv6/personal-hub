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


